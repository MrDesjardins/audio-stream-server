"""
Streaming and playback routes.
"""

import logging
import threading
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from config import get_config
from services.background_tasks import get_transcription_queue, TranscriptionJob
from services.database import (
    add_to_history,
    get_history,
    clear_history,
    get_queue_hash,
    save_playback_position,
    get_playback_position,
    clear_playback_position,
    get_playback_positions_batch,
)
from services.path_utils import expand_path
from services.streaming import (
    get_audio_duration,
    start_youtube_download,
    finish_youtube_download,
    is_download_in_progress,
)
from services.youtube import get_video_metadata, extract_video_id

logger = logging.getLogger(__name__)
router = APIRouter()
config = get_config()


class StreamRequest(BaseModel):
    youtube_video_id: str
    skip_transcription: bool = False
    queue_id: Optional[int] = None


class StreamState:
    """Thread-safe streaming state management."""

    def __init__(self, lock):
        self._lock = lock
        self._current_process = None
        self._download_thread = None
        self._current_video_id: Optional[str] = None
        self._current_queue_id: Optional[int] = None

    def start_stream(self, video_id: str, skip_transcription: bool):
        """Start new download, stopping existing one."""
        with self._lock:
            # Terminate existing download
            if self._current_process:
                logger.info("Stopping existing download")
                self._current_process.terminate()
                try:
                    self._current_process.wait(timeout=5)
                except Exception:
                    self._current_process.kill()
                self._current_process = None

        # Start the download process (returns immediately)
        proc = start_youtube_download(video_id)

        with self._lock:
            self._current_process = (
                proc  # Store immediately so stop_stream() can kill it
            )

        def target():
            if proc is not None:
                # Wait for download to complete
                proc.wait()
                # Handle rename and cleanup only if download succeeded
                finish_youtube_download(video_id, proc.returncode)
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

    @property
    def current_video_id(self) -> Optional[str]:
        with self._lock:
            return self._current_video_id

    @property
    def current_queue_id(self) -> Optional[int]:
        with self._lock:
            return self._current_queue_id

    def set_current(self, video_id: Optional[str], queue_id: Optional[int]) -> None:
        with self._lock:
            self._current_video_id = video_id
            self._current_queue_id = queue_id


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
def stream_video(request: StreamRequest) -> dict:
    """Start streaming a YouTube video."""
    state = get_stream_state()
    video_id = extract_video_id(request.youtube_video_id)

    logger.info(f"🎬 /stream requested for video: {video_id}")

    # Validate video ID
    if not video_id or video_id.strip() == "":
        logger.error("Received empty video_id in /stream request")
        raise HTTPException(
            status_code=400,
            detail="Invalid request: video_id is required and cannot be empty",
        )

    # Fetch video metadata and save to database
    try:
        metadata = get_video_metadata(video_id)
        if metadata:
            add_to_history(
                video_id,
                metadata["title"],
                metadata.get("channel"),
                metadata.get("thumbnail_url"),
            )
            logger.info(
                f"Added to history: {metadata['title']} by {metadata.get('channel')}"
            )
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
            job = TranscriptionJob(
                video_id=video_id, audio_path=config.get_audio_path(video_id)
            )
            queue.add_job(job)
            logger.info(
                f"Queued transcription job for {video_id} (will start after download)"
            )
        except Exception as e:
            logger.error(f"Failed to queue transcription job: {e}")
    elif config.transcription_enabled and request.skip_transcription:
        logger.info(f"Transcription skipped for {video_id} (user preference)")

    # Start new stream (handles stopping existing stream internally)
    state.start_stream(video_id, request.skip_transcription)
    state.set_current(video_id, request.queue_id)

    return {
        "status": "stream started",
        "youtube_video_id": video_id,
        "title": video_title,
    }


def _audio_is_ready(video_id: str) -> bool:
    """Check if the audio file exists and is not still being downloaded."""
    audio_path = expand_path(config.get_audio_path(video_id))
    return audio_path.exists() and not is_download_in_progress(video_id)


@router.get("/audio/{video_id}")
def get_audio_file(video_id: str) -> Response:
    """Serve the actual MP3 file for the player with mobile-optimized headers."""
    audio_path = expand_path(config.get_audio_path(video_id))

    if _audio_is_ready(video_id):
        file_size = audio_path.stat().st_size
        headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
            "Content-Length": str(file_size),
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "X-Audio-Duration",
            "Connection": "keep-alive",
        }
        duration = get_audio_duration(video_id)
        if duration is not None:
            headers["X-Audio-Duration"] = str(duration)

        # FileResponse automatically handles streaming, chunking, and seeking (Range headers)
        return FileResponse(
            path=audio_path,
            media_type="audio/mpeg",
            filename=f"{video_id}.mp3",
            headers=headers,
        )

    return JSONResponse(
        status_code=404,
        content={"error": "Audio not yet available", "status": "downloading"},
        headers={"Retry-After": "2"},
    )


@router.head("/audio/{video_id}")
def check_audio_file(video_id: str) -> JSONResponse:
    """Check if audio file exists and is ready (for polling). HEAD request."""
    audio_path = expand_path(config.get_audio_path(video_id))

    if _audio_is_ready(video_id):
        file_size = audio_path.stat().st_size
        headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
            "Content-Length": str(file_size),
            "Content-Type": "audio/mpeg",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "X-Audio-Duration",
        }
        duration = get_audio_duration(video_id)
        if duration is not None:
            headers["X-Audio-Duration"] = str(duration)
        return JSONResponse(status_code=200, content={}, headers=headers)

    return JSONResponse(status_code=404, content={}, headers={"Retry-After": "2"})


@router.post("/stop")
def stop_stream() -> dict:
    """Stop the current stream."""
    state = get_stream_state()
    if state.stop_stream():
        state.set_current(None, None)
        return {"status": "stream stopped"}
    raise HTTPException(status_code=400, detail="No stream running")


@router.get("/status")
def get_status() -> dict:
    """Get the current streaming status."""
    state = get_stream_state()
    try:
        queue_hash = get_queue_hash()
    except Exception as e:
        logger.warning(f"Failed to compute queue hash: {e}")
        queue_hash = 0
    return {
        "status": "streaming" if state.is_streaming() else "idle",
        "current_video_id": state.current_video_id,
        "current_queue_id": state.current_queue_id,
        "queue_hash": queue_hash,
    }


@router.get("/history")
def get_play_history(limit: int = 10) -> JSONResponse:
    """Get play history from database."""
    try:
        history = get_history(limit=limit)
        return JSONResponse({"history": [item.to_dict() for item in history]})
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/history/clear")
def clear_play_history() -> JSONResponse:
    """Clear all play history."""
    try:
        clear_history()
        return JSONResponse({"status": "cleared"})
    except Exception as e:
        logger.error(f"Error clearing history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SavePositionRequest(BaseModel):
    position_seconds: float
    duration_seconds: Optional[float] = None


@router.get("/playback-positions")
def get_positions_batch(ids: str = "") -> JSONResponse:
    """Get playback positions for multiple video IDs (comma-separated ?ids= param)."""
    youtube_ids = [vid.strip() for vid in ids.split(",") if vid.strip()]
    positions = get_playback_positions_batch(youtube_ids)
    return JSONResponse({vid: pos.to_dict() for vid, pos in positions.items()})


@router.get("/playback-position/{video_id}")
def get_position(video_id: str) -> JSONResponse:
    """Get the saved playback position for a video."""
    pos = get_playback_position(video_id)
    if pos is None:
        return JSONResponse({"position_seconds": 0, "duration_seconds": None})
    return JSONResponse(pos.to_dict())


@router.post("/playback-position/{video_id}")
def save_position(video_id: str, request: SavePositionRequest) -> JSONResponse:
    """Save or update the playback position for a video."""
    save_playback_position(video_id, request.position_seconds, request.duration_seconds)
    return JSONResponse({"status": "saved"})


@router.delete("/playback-position/{video_id}")
def delete_position(video_id: str) -> JSONResponse:
    """Delete the saved playback position for a video."""
    clear_playback_position(video_id)
    return JSONResponse({"status": "cleared"})
