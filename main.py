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
from config import get_config
from background_tasks import init_background_tasks, get_transcription_queue, TranscriptionJob, JobStatus

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


def start_youtube_stream(youtube_video_id: str):
    """Start yt-dlp -> ffmpeg streaming to stdout (and optionally save to file)"""
    global current_process
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

    # If transcription is enabled, save audio to file while streaming
    if config.transcription_enabled:
        audio_path = config.get_audio_path(youtube_video_id)
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
    current_process = ffmpeg_proc

    logger.info(f"Waiting for audio download and conversion to complete for video {youtube_video_id}...")
    ffmpeg_proc.wait()
    current_process = None
    logger.info(f"Audio download and conversion completed for video {youtube_video_id}")

    # Log the final file size if transcription is enabled
    if config.transcription_enabled and os.path.exists(audio_path):
        file_size = os.path.getsize(audio_path)
        logger.info(f"Audio file saved: {audio_path} ({file_size / 1024 / 1024:.2f} MB) - transcription job already queued")


@app.post("/stream")
def stream_video(request: StreamRequest):
    logger.info(f"🎬 /stream requested for video: {request.youtube_video_id}")
    logger.info(f"   Client should connect to: http://{host}:{api_port}/mystream")
    global ffmpeg_thread, current_process
    with process_lock:
        # Stop existing stream if any
        if current_process:
            logger.info(f"   Stopping existing stream")
            current_process.terminate()
            current_process = None

        # If transcription is enabled, queue the job immediately
        # The background worker will wait for the download to complete
        if config.transcription_enabled:
            try:
                queue = get_transcription_queue()
                job = TranscriptionJob(
                    video_id=request.youtube_video_id,
                    audio_path=config.get_audio_path(request.youtube_video_id)
                )
                queue.add_job(job)
                logger.info(f"Queued transcription job for {request.youtube_video_id} (will start after download)")
            except Exception as e:
                logger.error(f"Failed to queue transcription job: {e}")

        # Start new stream in a thread
        def target():
            start_youtube_stream(request.youtube_video_id)

        ffmpeg_thread = threading.Thread(target=target, daemon=True)
        ffmpeg_thread.start()
        return {"status": "stream started", "youtube_video_id": request.youtube_video_id}


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
