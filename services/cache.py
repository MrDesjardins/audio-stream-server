"""Caching service for transcripts, summaries, and audio files."""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime

from config import get_config

logger = logging.getLogger(__name__)


class TranscriptionCache:
    """Manages caching of transcripts and summaries."""

    def __init__(self, cache_dir: str = "/tmp/transcription-cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        logger.info(f"Transcription cache initialized at {self.cache_dir}")

    def _get_cache_path(self, video_id: str) -> Path:
        """Get the cache file path for a video."""
        return self.cache_dir / f"{video_id}.json"

    def get_cached(self, video_id: str) -> Optional[Dict[str, str]]:
        """
        Get cached transcript and summary for a video.

        Returns:
            Dict with 'transcript' and 'summary' keys, or None if not cached
        """
        cache_file = self._get_cache_path(video_id)

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, "r") as f:
                data = json.load(f)
            logger.info(f"Found cached transcript/summary for video {video_id}")
            return {"transcript": data.get("transcript"), "summary": data.get("summary")}
        except Exception as e:
            logger.error(f"Error reading cache for {video_id}: {e}")
            return None

    def save_transcript(self, video_id: str, transcript: str) -> None:
        """Save transcript to cache."""
        cache_file = self._get_cache_path(video_id)

        try:
            with self._lock:
                # Load existing data or create new
                data = {}
                if cache_file.exists():
                    with open(cache_file, "r") as f:
                        data = json.load(f)

                data["transcript"] = transcript
                data["transcript_timestamp"] = datetime.now().isoformat()

                with open(cache_file, "w") as f:
                    json.dump(data, f, indent=2)

            logger.info(f"Cached transcript for video {video_id}")
        except Exception as e:
            logger.error(f"Error saving transcript cache for {video_id}: {e}")

    def save_summary(self, video_id: str, summary: str) -> None:
        """Save summary to cache."""
        cache_file = self._get_cache_path(video_id)

        try:
            with self._lock:
                # Load existing data or create new
                data = {}
                if cache_file.exists():
                    with open(cache_file, "r") as f:
                        data = json.load(f)

                data["summary"] = summary
                data["summary_timestamp"] = datetime.now().isoformat()

                with open(cache_file, "w") as f:
                    json.dump(data, f, indent=2)

            logger.info(f"Cached summary for video {video_id}")
        except Exception as e:
            logger.error(f"Error saving summary cache for {video_id}: {e}")


class AudioCache:
    """Manages audio file caching with automatic cleanup."""

    def __init__(self, max_files: int = 10):
        self.max_files = max_files
        config = get_config()
        self.audio_dir = Path(config.temp_audio_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Audio cache initialized: max {max_files} files in {self.audio_dir}")

    def cleanup_old_files(self) -> None:
        """Remove oldest audio files if we exceed max_files limit."""
        try:
            # Get all mp3 files with their modification times
            audio_files = []
            for f in self.audio_dir.glob("*.mp3"):
                audio_files.append((f, f.stat().st_mtime))

            # Sort by modification time (oldest first)
            audio_files.sort(key=lambda x: x[1])

            # Remove oldest files if we exceed the limit
            files_to_remove = len(audio_files) - self.max_files
            if files_to_remove > 0:
                logger.info(
                    f"Cleaning up {files_to_remove} old audio files (limit: {self.max_files})"
                )
                for file_path, _ in audio_files[:files_to_remove]:
                    try:
                        file_path.unlink()
                        logger.info(f"Removed old audio file: {file_path.name}")
                    except Exception as e:
                        logger.error(f"Failed to remove {file_path}: {e}")
        except Exception as e:
            logger.error(f"Error during audio cache cleanup: {e}")

    def check_file_exists(self, video_id: str) -> bool:
        """Check if audio file for a video exists in cache."""
        audio_file = self.audio_dir / f"{video_id}.mp3"
        return audio_file.exists()


# Global cache instances
_transcript_cache: Optional[TranscriptionCache] = None
_audio_cache: Optional[AudioCache] = None
_cache_lock = threading.Lock()


def get_transcript_cache() -> TranscriptionCache:
    """Get the global transcript cache instance."""
    global _transcript_cache
    if _transcript_cache is None:
        with _cache_lock:
            if _transcript_cache is None:
                _transcript_cache = TranscriptionCache()
    return _transcript_cache


def get_audio_cache() -> AudioCache:
    """Get the global audio cache instance."""
    global _audio_cache
    if _audio_cache is None:
        with _cache_lock:
            if _audio_cache is None:
                max_files = int(os.environ.get("AUDIO_CACHE_MAX_FILES", "10"))
                _audio_cache = AudioCache(max_files=max_files)
    return _audio_cache
