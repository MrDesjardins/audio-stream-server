"""Background prefetching for queued YouTube audio."""

import logging
import threading
from queue import Empty, Queue
from subprocess import Popen
from typing import Literal, Optional

from services.cache import get_audio_cache
from services.streaming import (
    finish_youtube_download,
    is_download_in_progress,
    start_youtube_download,
)

logger = logging.getLogger(__name__)

AudioPrefetchStatus = Literal["queued", "downloading", "cached", "failed", "idle"]


class AudioPrefetcher:
    """Single-worker FIFO downloader for warming queued audio files."""

    def __init__(self) -> None:
        self._queue: Queue[str] = Queue()
        self._queued_video_ids: set[str] = set()
        self._failed_video_ids: set[str] = set()
        self._current_video_id: Optional[str] = None
        self._current_process: Optional[Popen] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="audio-prefetcher",
            daemon=True,
        )
        self._thread.start()

    def enqueue(self, video_id: str) -> AudioPrefetchStatus:
        """Add a video to the prefetch queue if needed."""
        if self._is_cached(video_id):
            return "cached"

        if is_download_in_progress(video_id):
            return "downloading"

        with self._lock:
            if video_id == self._current_video_id:
                return "downloading"

            if video_id in self._queued_video_ids:
                return "queued"

            self._failed_video_ids.discard(video_id)
            self._queued_video_ids.add(video_id)
            self._queue.put(video_id)

        logger.info("Queued audio prefetch for %s", video_id)
        return "queued"

    def get_status(self, video_id: str) -> AudioPrefetchStatus:
        """Return current readiness status for a video."""
        if self._is_cached(video_id):
            return "cached"

        if is_download_in_progress(video_id):
            return "downloading"

        with self._lock:
            if video_id == self._current_video_id:
                return "downloading"
            if video_id in self._queued_video_ids:
                return "queued"
            if video_id in self._failed_video_ids:
                return "failed"

        return "idle"

    def stop(self) -> None:
        """Stop the worker and terminate an active prefetch process."""
        self._stop_event.set()
        with self._lock:
            proc = self._current_process

        if proc is not None and proc.poll() is None:
            logger.info("Stopping active audio prefetch")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

        self._thread.join(timeout=5)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                video_id = self._queue.get(timeout=0.5)
            except Empty:
                continue

            try:
                self._prefetch(video_id)
            except Exception as e:
                logger.error("Unexpected prefetch error for %s: %s", video_id, e)
                self._mark_failed(video_id)
            finally:
                self._queue.task_done()

    def _prefetch(self, video_id: str) -> None:
        with self._lock:
            self._queued_video_ids.discard(video_id)
            self._current_video_id = video_id

        try:
            if self._is_cached(video_id):
                logger.info("Prefetch %s: already cached", video_id)
                return

            if is_download_in_progress(video_id):
                logger.info("Prefetch %s: download already in progress", video_id)
                return

            logger.info("Prefetch %s: starting download", video_id)
            proc = start_youtube_download(video_id)

            if proc is None:
                if self._is_cached(video_id) or is_download_in_progress(video_id):
                    return
                self._mark_failed(video_id)
                return

            with self._lock:
                self._current_process = proc

            proc.wait()
            finish_youtube_download(video_id, proc.returncode)

            if proc.returncode == 0 and self._is_cached(video_id):
                with self._lock:
                    self._failed_video_ids.discard(video_id)
                logger.info("Prefetch %s: cached", video_id)
            else:
                self._mark_failed(video_id)
        finally:
            with self._lock:
                if self._current_video_id == video_id:
                    self._current_video_id = None
                self._current_process = None

    def _mark_failed(self, video_id: str) -> None:
        with self._lock:
            self._failed_video_ids.add(video_id)
        logger.warning("Prefetch %s: failed", video_id)

    def _is_cached(self, video_id: str) -> bool:
        return get_audio_cache().check_file_exists(video_id)


_audio_prefetcher: Optional[AudioPrefetcher] = None
_audio_prefetcher_lock = threading.Lock()


def init_audio_prefetcher() -> AudioPrefetcher:
    """Initialize and return the global prefetch worker."""
    global _audio_prefetcher
    if _audio_prefetcher is None:
        with _audio_prefetcher_lock:
            if _audio_prefetcher is None:
                _audio_prefetcher = AudioPrefetcher()
    return _audio_prefetcher


def get_audio_prefetcher() -> AudioPrefetcher:
    """Return the global prefetch worker, initializing it if needed."""
    return init_audio_prefetcher()


def shutdown_audio_prefetcher() -> None:
    """Stop the global prefetch worker if it was initialized."""
    global _audio_prefetcher
    if _audio_prefetcher is not None:
        _audio_prefetcher.stop()
        _audio_prefetcher = None


def enqueue_audio_prefetch(video_id: str) -> AudioPrefetchStatus:
    """Queue a video for background audio download."""
    return get_audio_prefetcher().enqueue(video_id)


def get_audio_prefetch_status(video_id: str) -> AudioPrefetchStatus:
    """Return queue audio readiness status."""
    return get_audio_prefetcher().get_status(video_id)
