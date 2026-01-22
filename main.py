# file: youtube_streamer.py
import os
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import subprocess
import threading

# Load environment variables from .env file FIRST
load_dotenv()

# Import transcription modules
from cache_service import get_audio_cache
from config import get_config
from background_tasks import init_background_tasks, get_transcription_queue, TranscriptionJob, JobStatus

# Import database and YouTube utilities
from database_service import (
    init_database, add_to_history, get_history, clear_history,
    add_to_queue, get_queue, get_next_in_queue, remove_from_queue, clear_queue
)
from youtube_utils import get_video_title, extract_video_id

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/audio-transcription.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configurable host and port (loaded after load_dotenv())
host = os.environ.get("FASTAPI_HOST", "127.0.0.1")
api_port = int(os.environ.get("FASTAPI_API_PORT", 8000))

# Log the server configuration immediately
logger.info(f"=" * 60)
logger.info(f"SERVER CONFIGURATION")
logger.info(f"FASTAPI_HOST: {host}")
logger.info(f"FASTAPI_API_PORT: {api_port}")
logger.info(f"Stream URL will be: http://{host}:{api_port}/mystream")
logger.info(f"=" * 60)

app = FastAPI()

# Load configuration
config = get_config()

# Initialize database
logger.info("Initializing database")
init_database()

# Initialize background tasks if transcription is enabled
if config.transcription_enabled:
    logger.info("Transcription enabled - initializing background tasks")
    # Create temp audio directory
    os.makedirs(config.temp_audio_dir, exist_ok=True)
    init_background_tasks()
else:
    logger.info("Transcription disabled")

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Global process/thread for streaming
current_process = None
ffmpeg_thread = None
process_lock = threading.Lock()  # Ensure thread safety


class StreamRequest(BaseModel):
    youtube_video_id: str
    skip_transcription: bool = False


def start_youtube_stream(youtube_video_id: str, skip_transcription: bool = False):
    """Start yt-dlp -> ffmpeg streaming to stdout (and optionally save to file)"""
    global current_process
    audio_cache = get_audio_cache()
    audio_path = config.get_audio_path(youtube_video_id)
    
    # If audio file already exists in cache, no need to save again
    if not audio_cache.check_file_exists(youtube_video_id):
        url = f"https://www.youtube.com/watch?v={youtube_video_id}"
        yt_cmd = [
        "/usr/local/bin/yt-dlp",
        "-f",
        "bestaudio",
        "--extract-audio",
        "--audio-format", "mp3",
        "-o", "-",  # output to stdout
        url
        ]

        # If transcription is enabled and not skipped, save audio to file while streaming
        if config.transcription_enabled and not skip_transcription:
            logger.info(f"Saving audio to {audio_path} while streaming")

            # Use tee to write to both stdout and file
            # Must specify codec and map stream explicitly for tee muxer
            ffmpeg_cmd = [
                "ffmpeg",
                "-i", "pipe:0",
                "-map", "0:a",          # Map the audio stream
                "-c:a", "libmp3lame",   # Explicitly specify MP3 encoder
                "-q:a", "2",            # Quality setting (0-9, lower is better)
                "-f", "tee",
                f"[f=mp3]pipe:1|[f=mp3]{audio_path}",
            ]
        else:
            # Standard streaming without saving
            ffmpeg_cmd = [
                "ffmpeg",
                "-i", "pipe:0",
                "-f", "mp3",
                "pipe:1",
            ]
        yt_proc = subprocess.Popen(yt_cmd, stdout=subprocess.PIPE)
        ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=yt_proc.stdout, stdout=subprocess.PIPE)
        yt_proc.stdout.close()
       
    else:
        logger.info(f"Audio file for video {youtube_video_id} already in cache, streaming from cache")
        # Stream the cached file
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", audio_path,
            "-f", "mp3",
            "pipe:1",
        ]
        ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE)
        
    current_process = ffmpeg_proc
    logger.info(f"Waiting for audio download and conversion to complete for video {youtube_video_id}...")
    ffmpeg_proc.wait()
    current_process = None
    logger.info(f"Audio download and conversion completed for video {youtube_video_id}")

    # Log the final file size if transcription is enabled and not skipped
    if config.transcription_enabled and not skip_transcription and os.path.exists(audio_path):
        file_size = os.path.getsize(audio_path)
        logger.info(f"Audio file saved: {audio_path} ({file_size / 1024 / 1024:.2f} MB) - transcription job already queued")


@app.post("/stream")
def stream_video(request: StreamRequest):
    # Extract video ID from URL if needed
    video_id = extract_video_id(request.youtube_video_id)

    logger.info(f"🎬 /stream requested for video: {video_id}")
    logger.info(f"   Client should connect to: http://{host}:{api_port}/mystream")

    # Fetch video title and save to database
    try:
        video_title = get_video_title(video_id)
        if video_title:
            add_to_history(video_id, video_title)
            logger.info(f"Added to history: {video_title}")
        else:
            # Fallback title if we couldn't fetch it
            add_to_history(video_id, f"YouTube Video {video_id}")
            logger.warning(f"Could not fetch title for {video_id}, using fallback")
    except Exception as e:
        logger.error(f"Error saving to history: {e}")
        # Don't fail the stream if history saving fails

    global ffmpeg_thread, current_process
    with process_lock:
        # Stop existing stream if any
        if current_process:
            logger.info(f"   Stopping existing stream")
            current_process.terminate()
            current_process = None

        # If transcription is enabled and not skipped, queue the job immediately
        # The background worker will wait for the download to complete
        if config.transcription_enabled and not request.skip_transcription:
            try:
                queue = get_transcription_queue()
                job = TranscriptionJob(
                    video_id=video_id,
                    audio_path=config.get_audio_path(video_id)
                )
                queue.add_job(job)
                logger.info(f"Queued transcription job for {video_id} (will start after download)")
            except Exception as e:
                logger.error(f"Failed to queue transcription job: {e}")
        elif config.transcription_enabled and request.skip_transcription:
            logger.info(f"Transcription skipped for {video_id} (user preference)")

        # Start new stream in a thread
        def target():
            start_youtube_stream(video_id, request.skip_transcription)

        ffmpeg_thread = threading.Thread(target=target, daemon=True)
        ffmpeg_thread.start()
        return {"status": "stream started", "youtube_video_id": video_id, "title": video_title}


@app.post("/stop")
def stop_stream():
    global current_process
    with process_lock:
        if current_process:
            current_process.terminate()
            current_process = None
            return {"status": "stream stopped"}
        else:
            raise HTTPException(status_code=400, detail="No stream running")


@app.get("/status")
def get_status():
    return {"status": "streaming" if current_process else "idle"}


@app.get("/history")
def get_play_history(limit: int = 10):
    """Get play history from database."""
    try:
        history = get_history(limit)
        return JSONResponse({"history": history})
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/history/clear")
def clear_play_history():
    """Clear all play history."""
    try:
        clear_history()
        return JSONResponse({"status": "cleared"})
    except Exception as e:
        logger.error(f"Error clearing history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Queue endpoints
@app.post("/queue/add")
def add_video_to_queue(request: StreamRequest):
    """Add a video to the queue."""
    try:
        # Extract video ID from URL if needed
        video_id = extract_video_id(request.youtube_video_id)

        # Fetch video title
        video_title = get_video_title(video_id)
        if not video_title:
            video_title = f"YouTube Video {video_id}"

        # Add to queue
        queue_id = add_to_queue(video_id, video_title)

        return JSONResponse({
            "status": "added",
            "queue_id": queue_id,
            "youtube_id": video_id,
            "title": video_title
        })
    except Exception as e:
        logger.error(f"Error adding to queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/queue")
def get_current_queue():
    """Get the current queue."""
    try:
        queue = get_queue()
        return JSONResponse({"queue": queue})
    except Exception as e:
        logger.error(f"Error fetching queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/queue/{queue_id}")
def remove_from_queue_endpoint(queue_id: int):
    """Remove an item from the queue."""
    try:
        success = remove_from_queue(queue_id)
        if success:
            return JSONResponse({"status": "removed", "queue_id": queue_id})
        else:
            raise HTTPException(status_code=404, detail="Queue item not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing from queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/queue/next")
def play_next_in_queue():
    """Remove current item and start playing the next item in queue."""
    try:
        next_item = get_next_in_queue()

        if not next_item:
            return JSONResponse({
                "status": "queue_empty",
                "message": "No more items in queue"
            })

        # Remove the current first item
        remove_from_queue(next_item['id'])

        # Get the new first item (which was second)
        next_item = get_next_in_queue()

        if not next_item:
            return JSONResponse({
                "status": "queue_empty",
                "message": "No more items in queue"
            })

        return JSONResponse({
            "status": "next",
            "youtube_id": next_item['youtube_id'],
            "title": next_item['title'],
            "queue_id": next_item['id']
        })
    except Exception as e:
        logger.error(f"Error playing next in queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/queue/clear")
def clear_current_queue():
    """Clear all items from the queue."""
    try:
        clear_queue()
        return JSONResponse({"status": "cleared"})
    except Exception as e:
        logger.error(f"Error clearing queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/mystream")
def stream_audio(request: Request):
    """Serve current ffmpeg stdout as audio"""
    logger.info(f"🎵 /mystream accessed by {request.client.host}:{request.client.port}")
    if current_process is None:
        logger.warning(f"❌ No active stream when /mystream was accessed")
        raise HTTPException(status_code=400, detail="No active stream")
    logger.info(f"✓ Streaming audio to client")
    return StreamingResponse(current_process.stdout, media_type="audio/mpeg")


@app.get("/")
def index(request: Request):
    # Use the request's host header to get the actual server address clients use
    # This handles 0.0.0.0 binding correctly
    server_host = request.url.hostname
    logger.info(f"📄 Index page requested by {request.client.host}")
    logger.info(f"   Request URL: {request.url}")
    logger.info(f"   Server hostname from request: {server_host}")
    logger.info(f"   Audio player URL will be: http://{server_host}:{api_port}/mystream")
    return templates.TemplateResponse("index.html", {
        "request": request,
        "host": server_host,  # Use the hostname from the request, not the bind address
        "api_port": api_port,
        "transcription_enabled": config.transcription_enabled
    })


# Transcription endpoints
@app.get("/transcription/status/{video_id}")
def get_transcription_status(video_id: str):
    """Get the transcription status for a specific video."""
    if not config.transcription_enabled:
        raise HTTPException(status_code=400, detail="Transcription not enabled")

    try:
        queue = get_transcription_queue()
        job = queue.get_job_status(video_id)

        if job is None:
            return JSONResponse({
                "video_id": video_id,
                "status": "not_found",
                "error": None,
                "trilium_note_id": None,
                "trilium_note_url": None,
                "summary": None
            })

        return JSONResponse({
            "video_id": video_id,
            "status": job.status.value,
            "error": job.error,
            "trilium_note_id": job.trilium_note_id,
            "trilium_note_url": job.trilium_note_url,
            "summary": job.summary
        })

    except Exception as e:
        logger.error(f"Error getting transcription status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/transcription/start/{video_id}")
def start_transcription(video_id: str):
    """Manually trigger transcription for a video (if audio file exists)."""
    if not config.transcription_enabled:
        raise HTTPException(status_code=400, detail="Transcription not enabled")

    audio_path = config.get_audio_path(video_id)

    if not os.path.exists(audio_path):
        raise HTTPException(
            status_code=404,
            detail=f"Audio file not found for video {video_id}. Please stream the video first."
        )

    try:
        queue = get_transcription_queue()
        job = TranscriptionJob(
            video_id=video_id,
            audio_path=audio_path
        )
        queue.add_job(job)

        return JSONResponse({
            "status": "queued",
            "video_id": video_id
        })

    except Exception as e:
        logger.error(f"Error starting transcription: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/transcription/summary/{video_id}")
def get_summary(video_id: str):
    """Get the summary for a specific video if available."""
    if not config.transcription_enabled:
        raise HTTPException(status_code=400, detail="Transcription not enabled")

    try:
        queue = get_transcription_queue()
        job = queue.get_job_status(video_id)

        if job is None:
            raise HTTPException(status_code=404, detail=f"No transcription found for video {video_id}")

        if job.status not in [JobStatus.COMPLETED, JobStatus.SKIPPED]:
            return JSONResponse({
                "video_id": video_id,
                "status": job.status.value,
                "summary": None,
                "error": "Transcription not yet completed"
            })

        return JSONResponse({
            "video_id": video_id,
            "status": job.status.value,
            "summary": job.summary,
            "trilium_note_url": job.trilium_note_url
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    print("=" * 70)
    print(f"🚀 STARTING AUDIO STREAM SERVER")
    print(f"   Host: {host}")
    print(f"   Port: {api_port}")
    print(f"   Stream URL: http://{host}:{api_port}/mystream")
    print(f"   Transcription: {'enabled' if config.transcription_enabled else 'disabled'}")
    print("=" * 70)
    uvicorn.run("main:app", host=host, port=api_port, reload=True)
