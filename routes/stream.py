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
from services.youtube import get_video_metadata, extract_video_id

logger = logging.getLogger(__name__)
router = APIRouter()
config = get_config()


class StreamRequest(BaseModel):
    youtube_video_id: str
    skip_transcription: bool = False


class StreamState:
    """Thread-safe streaming state management."""

    def __init__(self, lock, broadcaster):
        self._lock = lock
        self._broadcaster = broadcaster
        self._current_process = None
        self._ffmpeg_thread = None

    def start_stream(self, video_id: str, skip_transcription: bool):
        """Start new stream, stopping existing one."""
        from services.streaming import start_youtube_stream
        from services.broadcast import StreamBroadcaster

        with self._lock:
            # Terminate existing stream
            if self._current_process:
                logger.info("Stopping existing stream")
                self._current_process.terminate()
                try:
                    self._current_process.wait(timeout=5)
                except Exception:
                    self._current_process.kill()

            # Stop old broadcaster
            self._broadcaster.stop()

            # Create new broadcaster
            self._broadcaster = StreamBroadcaster()

            # Start new stream in a thread
            def target():
                self._current_process = start_youtube_stream(video_id, skip_transcription, self._broadcaster)
                with self._lock:
                    self._current_process = None

            self._ffmpeg_thread = threading.Thread(target=target, daemon=True)
            self._ffmpeg_thread.start()

            return self._broadcaster

    def stop_stream(self) -> bool:
        """Stop current stream."""
        with self._lock:
            if self._current_process:
                self._current_process.terminate()
                try:
                    self._current_process.wait(timeout=5)
                except Exception:
                    self._current_process.kill()
                self._current_process = None
                self._broadcaster.stop()
                return True
            return False

    def is_streaming(self) -> bool:
        """Check if currently streaming."""
        with self._lock:
            return self._current_process is not None

    @property
    def broadcaster(self):
        """Get current broadcaster (read-only)."""
        return self._broadcaster


# Global instance
_stream_state = None


def init_stream_globals(proc_lock, bc):
    """Initialize global state from main.py."""
    global _stream_state
    _stream_state = StreamState(proc_lock, bc)


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
                video_id,
                metadata["title"],
                metadata.get("channel"),
                metadata.get("thumbnail_url")
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

    # Start new stream (handles stopping existing stream internally)
    state.start_stream(video_id, request.skip_transcription)

    return {"status": "stream started", "youtube_video_id": video_id, "title": video_title}


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


@router.get("/mystream")
async def stream_audio(request: Request):
    """Serve current ffmpeg stdout as audio (with multi-client support)."""
    state = get_stream_state()
    logger.info(f"🎵 /mystream accessed by {request.client.host}:{request.client.port}")

    if not state.broadcaster.is_active():
        logger.warning(f"❌ No active stream when /mystream was accessed")
        raise HTTPException(status_code=400, detail="No active stream")

    logger.info(f"✓ Streaming audio to client (broadcaster active with {len(state.broadcaster.clients)} clients)")

    # Subscribe to broadcaster
    client_queue = state.broadcaster.subscribe()

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
                    if not state.broadcaster.is_active():
                        logger.info(f"Stream ended (broadcaster inactive) for client {request.client.host}")
                        break

        except asyncio.CancelledError:
            logger.info(f"Client {request.client.host} disconnected")
        except Exception as e:
            logger.error(f"Error streaming to client {request.client.host}: {e}")
        finally:
            # Unsubscribe client when done
            state.broadcaster.unsubscribe(client_queue)

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
