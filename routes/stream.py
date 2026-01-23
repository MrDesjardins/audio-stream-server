"""
Streaming and playback routes.
"""
import logging
import threading
import asyncio
import queue
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from config import get_config
from services.background_tasks import get_transcription_queue, TranscriptionJob
from services.streaming import start_youtube_stream
from services.database import add_to_history, get_history, clear_history
from services.youtube import get_video_title, extract_video_id

logger = logging.getLogger(__name__)
router = APIRouter()
config = get_config()


class StreamRequest(BaseModel):
    youtube_video_id: str
    skip_transcription: bool = False


# Global state (will be set by main.py)
current_process = None
ffmpeg_thread = None
process_lock = None
broadcaster = None


def init_stream_globals(proc_lock, bc):
    """Initialize global state from main.py."""
    global process_lock, broadcaster
    process_lock = proc_lock
    broadcaster = bc


@router.post("/stream")
def stream_video(request: StreamRequest):
    """Start streaming a YouTube video."""
    video_id = extract_video_id(request.youtube_video_id)

    logger.info(f"🎬 /stream requested for video: {video_id}")

    # Fetch video title and save to database
    try:
        video_title = get_video_title(video_id)
        if video_title:
            add_to_history(video_id, video_title)
            logger.info(f"Added to history: {video_title}")
        else:
            add_to_history(video_id, f"YouTube Video {video_id}")
            logger.warning(f"Could not fetch title for {video_id}, using fallback")
    except Exception as e:
        logger.error(f"Error saving to history: {e}")

    global ffmpeg_thread, current_process, broadcaster
    with process_lock:
        # Stop existing stream if any
        if current_process:
            logger.info(f"   Stopping existing stream")
            current_process.terminate()
            current_process = None
            broadcaster.stop()

        # Create new broadcaster for this stream
        from services.broadcast import StreamBroadcaster
        broadcaster = StreamBroadcaster()

        # Queue transcription job if enabled
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
            global current_process
            current_process = start_youtube_stream(video_id, request.skip_transcription, broadcaster)
            current_process = None

        ffmpeg_thread = threading.Thread(target=target, daemon=True)
        ffmpeg_thread.start()
        return {"status": "stream started", "youtube_video_id": video_id, "title": video_title}


@router.post("/stop")
def stop_stream():
    """Stop the current stream."""
    global current_process
    with process_lock:
        if current_process:
            current_process.terminate()
            current_process = None
            return {"status": "stream stopped"}
        else:
            raise HTTPException(status_code=400, detail="No stream running")


@router.get("/status")
def get_status():
    """Get the current streaming status."""
    return {"status": "streaming" if current_process else "idle"}


@router.get("/mystream")
async def stream_audio(request: Request):
    """Serve current ffmpeg stdout as audio (with multi-client support)."""
    logger.info(f"🎵 /mystream accessed by {request.client.host}:{request.client.port}")

    if not broadcaster.is_active():
        logger.warning(f"❌ No active stream when /mystream was accessed")
        raise HTTPException(status_code=400, detail="No active stream")

    logger.info(f"✓ Streaming audio to client (broadcaster active with {len(broadcaster.clients)} clients)")

    # Subscribe to broadcaster
    client_queue = broadcaster.subscribe()

    async def stream_generator():
        """Generate stream chunks from broadcaster queue."""
        try:
            while True:
                try:
                    # Wait for next chunk from broadcaster
                    chunk = await asyncio.to_thread(client_queue.get, timeout=1.0)

                    # None signals end of stream
                    if chunk is None:
                        logger.info(f"Stream ended for client {request.client.host}")
                        break

                    yield chunk

                except queue.Empty:
                    # Timeout waiting for chunk, check if stream is still active
                    if not broadcaster.is_active():
                        logger.info(f"Stream ended (broadcaster inactive) for client {request.client.host}")
                        break

        except asyncio.CancelledError:
            logger.info(f"Client {request.client.host} disconnected")
        except Exception as e:
            logger.error(f"Error streaming to client {request.client.host}: {e}")
        finally:
            # Unsubscribe client when done
            broadcaster.unsubscribe(client_queue)

    return StreamingResponse(stream_generator(), media_type="audio/mpeg")


@router.get("/history")
def get_play_history(limit: int = 10):
    """Get play history from database."""
    try:
        history = get_history(limit=limit)
        return JSONResponse({"history": history})
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/history/clear")
def clear_play_history():
    """Clear all play history."""
    try:
        clear_history()
        return JSONResponse({"status": "cleared"})
    except Exception as e:
        logger.error(f"Error clearing history: {e}")
        raise HTTPException(status_code=500, detail=str(e))
