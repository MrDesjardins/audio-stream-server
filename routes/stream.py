"""
Streaming and playback routes.
"""

import logging
import os
import threading
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from config import get_config
from services.background_tasks import get_transcription_queue, TranscriptionJob
from services.database import add_to_history, get_history, clear_history
from services.youtube import get_video_metadata, extract_video_id

logger = logging.getLogger(__name__)
router = APIRouter()
config = get_config()


class StreamRequest(BaseModel):
    youtube_video_id: str
    skip_transcription: bool = False


class StreamState:
    """Thread-safe streaming state management."""

    def __init__(self, lock):
        self._lock = lock
        self._current_process = None
        self._download_thread = None

    def start_stream(self, video_id: str, skip_transcription: bool):
        """Start new download, stopping existing one."""
        from services.streaming import start_youtube_download

        with self._lock:
            # Terminate existing download
            if self._current_process:
                logger.info("Stopping existing download")
                self._current_process.terminate()
                try:
                    self._current_process.wait(timeout=5)
                except Exception:
                    self._current_process.kill()

            # Start new download in a thread
            def target():
                self._current_process = start_youtube_download(
                    video_id, skip_transcription
                )
                with self._lock:
                    self._current_process = None

            self._download_thread = threading.Thread(target=target, daemon=True)
            self._download_thread.start()

    def stop_stream(self) -> bool:
        """Stop current download."""
        with self._lock:
            if self._current_process:
                self._current_process.terminate()
                try:
                    self._current_process.wait(timeout=5)
                except Exception:
                    self._current_process.kill()
                self._current_process = None
                return True
            return False

    def is_streaming(self) -> bool:
        """Check if currently downloading."""
        with self._lock:
            return self._current_process is not None


# Global instance
_stream_state = None


def init_stream_globals(proc_lock):
    """Initialize global state from main.py."""
    global _stream_state
    _stream_state = StreamState(proc_lock)


def get_stream_state() -> StreamState:
    """Get stream state singleton."""
    if _stream_state is None:
        raise RuntimeError("Stream state not initialized")
    return _stream_state


@router.post("/stream")
def stream_video(request: StreamRequest):
    """Start streaming a YouTube video."""
    state = get_stream_state()
    video_id = extract_video_id(request.youtube_video_id)

    logger.info(f"🎬 /stream requested for video: {video_id}")

    # Fetch video metadata and save to database
    try:
        metadata = get_video_metadata(video_id)
        if metadata:
            add_to_history(
                video_id, metadata["title"], metadata.get("channel"), metadata.get("thumbnail_url")
            )
            logger.info(f"Added to history: {metadata['title']} by {metadata.get('channel')}")
            video_title = metadata["title"]
        else:
            add_to_history(video_id, f"YouTube Video {video_id}")
            logger.warning(f"Could not fetch metadata for {video_id}, using fallback")
            video_title = f"YouTube Video {video_id}"
    except Exception as e:
        logger.error(f"Error saving to history: {e}")
        video_title = f"YouTube Video {video_id}"

    # Queue transcription job if enabled
    if config.transcription_enabled and not request.skip_transcription:
        try:
            queue = get_transcription_queue()
            job = TranscriptionJob(video_id=video_id, audio_path=config.get_audio_path(video_id))
            queue.add_job(job)
            logger.info(f"Queued transcription job for {video_id} (will start after download)")
        except Exception as e:
            logger.error(f"Failed to queue transcription job: {e}")
    elif config.transcription_enabled and request.skip_transcription:
        logger.info(f"Transcription skipped for {video_id} (user preference)")

    # Start new stream (handles stopping existing stream internally)
    state.start_stream(video_id, request.skip_transcription)

    return {"status": "stream started", "youtube_video_id": video_id, "title": video_title,}

@router.get("/audio/{video_id}")
def get_audio_file(video_id: str):
    """Serve the actual MP3 file for the player with mobile-optimized headers."""
    audio_path = config.get_audio_path(video_id) # e.g., /tmp/audio-transcriptions/video_id.mp3

    if os.path.exists(audio_path):
        # Get file size for progress tracking
        file_size = os.path.getsize(audio_path)

        # FileResponse automatically handles streaming, chunking, and seeking (Range headers)
        return FileResponse(
            path=audio_path,
            media_type='audio/mpeg',
            filename=f"{video_id}.mp3",
            headers={
                # Enable byte-range requests for seeking (mobile browsers rely on this)
                "Accept-Ranges": "bytes",
                # Allow aggressive caching once file is complete
                "Cache-Control": "public, max-age=3600",
                # Provide file size for download progress
                "Content-Length": str(file_size),
                # Allow CORS for cross-origin requests
                "Access-Control-Allow-Origin": "*",
                # Keep connection alive for mobile
                "Connection": "keep-alive",
            }
        )

    return JSONResponse(
        status_code=404,
        content={"error": "Audio not yet available", "status": "downloading"},
        headers={"Retry-After": "2"}  # Suggest retry after 2 seconds
    )

@router.head("/audio/{video_id}")
def check_audio_file(video_id: str):
    """Check if audio file exists (for polling) - HEAD request returns headers only."""
    audio_path = config.get_audio_path(video_id)

    if os.path.exists(audio_path):
        file_size = os.path.getsize(audio_path)
        return JSONResponse(
            status_code=200,
            content={},  # HEAD requests should have empty body
            headers={
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=3600",
                "Content-Length": str(file_size),
                "Content-Type": "audio/mpeg",
                "Access-Control-Allow-Origin": "*",
            }
        )

    return JSONResponse(
        status_code=404,
        content={},  # HEAD requests should have empty body
        headers={"Retry-After": "2"}
    )

@router.post("/stop")
def stop_stream():
    """Stop the current stream."""
    state = get_stream_state()
    if state.stop_stream():
        return {"status": "stream stopped"}
    raise HTTPException(status_code=400, detail="No stream running")


@router.get("/status")
def get_status():
    """Get the current streaming status."""
    state = get_stream_state()
    return {"status": "streaming" if state.is_streaming() else "idle"}


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
