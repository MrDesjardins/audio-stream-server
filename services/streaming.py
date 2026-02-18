"""
YouTube audio download service.

Downloads audio from YouTube using yt-dlp and saves as MP3.
"""

import json
import logging
import os
import subprocess
from typing import Optional

from services.cache import get_audio_cache
from services.path_utils import expand_path, expand_path_str
from config import get_config

logger = logging.getLogger(__name__)
config = get_config()

_audio_duration_cache: dict[str, float] = {}


def get_audio_duration(youtube_video_id: str) -> Optional[float]:
    """Return duration in seconds from ffprobe. Cached per session."""
    if youtube_video_id in _audio_duration_cache:
        return _audio_duration_cache[youtube_video_id]

    audio_path = expand_path(config.get_audio_path(youtube_video_id))
    if not audio_path.exists():
        return None

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
        _audio_duration_cache[youtube_video_id] = duration
        return duration
    except Exception as e:
        logger.warning(f"ffprobe failed for {youtube_video_id}: {e}")
        return None


def _get_download_marker(youtube_video_id: str) -> str:
    """Get the path for the download-in-progress marker file."""
    return os.path.join(config.temp_audio_dir, f"{youtube_video_id}.downloading")


def is_download_in_progress(youtube_video_id: str) -> bool:
    """Check if a download is currently in progress for this video."""
    return expand_path(_get_download_marker(youtube_video_id)).exists()


def start_youtube_download(youtube_video_id: str):
    """
    Start downloading audio from YouTube. Returns the process immediately
    so the caller can store it and terminate if needed.

    Call finish_youtube_download() after proc.wait() to handle cleanup.

    Args:
        youtube_video_id: YouTube video ID
        skip_transcription: Unused, kept for API compatibility

    Returns:
        proc or None if already cached
    """
    audio_cache = get_audio_cache()
    audio_path = expand_path(config.get_audio_path(youtube_video_id))

    if audio_cache.check_file_exists(youtube_video_id):
        logger.info(f"Audio file for video {youtube_video_id} already exists in cache")
        return None

    logger.info(f"Downloading audio for video {youtube_video_id}")
    url = f"https://www.youtube.com/watch?v={youtube_video_id}"

    # Create marker file so the /audio endpoint won't serve a partial file
    marker_path = expand_path(_get_download_marker(youtube_video_id))
    try:
        marker_path.touch(exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create download marker: {e}")

    stderr_path = str(audio_path) + ".err"

    # Use yt-dlp to download and convert directly to MP3.
    # -o uses the base path WITHOUT extension — yt-dlp appends .mp3 via --audio-format.
    # Passing -o with .mp3 extension causes yt-dlp to create path.mp3.mp3.
    # --extract-audio handles the ffmpeg conversion internally.
    base_path = expand_path_str(os.path.join(config.temp_audio_dir, youtube_video_id))
    yt_cmd = [
        "/usr/local/bin/yt-dlp",
        "-f",
        "bestaudio/best",
        "--extract-audio",
        "--audio-format",
        "mp3",
        "--audio-quality",
        str(config.audio_quality),  # VBR 0-9 from AUDIO_QUALITY env var
        "--no-playlist",
        "--extractor-args",
        "youtube:player_client=android",
        "-o",
        base_path,  # No extension — yt-dlp adds .mp3
        url,
    ]

    try:
        # Write stderr to a file to avoid pipe buffer deadlock on long downloads
        with open(stderr_path, "w") as stderr_file:
            proc = subprocess.Popen(
                yt_cmd,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
            )

        logger.info(
            f"Started downloading audio for video {youtube_video_id} to {audio_path}"
        )
        return proc

    except Exception as e:
        logger.error(f"Exception starting download for {youtube_video_id}: {e}")
        # Clean up marker on failure to start
        try:
            if marker_path.exists():
                marker_path.unlink()
        except Exception:
            pass
        return None


def finish_youtube_download(youtube_video_id: str, returncode: int):
    """
    Handle post-download cleanup: remove marker file, log errors on failure.
    Call this after proc.wait() completes in the download thread.

    Args:
        youtube_video_id: YouTube video ID
        returncode: Process exit code (0 = success)
    """
    audio_path = expand_path(config.get_audio_path(youtube_video_id))
    marker_path = expand_path(_get_download_marker(youtube_video_id))
    stderr_path = expand_path(config.get_audio_path(youtube_video_id) + ".err")

    # Read stderr for error reporting
    error_output = ""
    try:
        with open(stderr_path, "r") as f:
            error_output = f.read()[-500:]
    except Exception:
        pass

    # Clean up stderr file
    try:
        if stderr_path.exists():
            stderr_path.unlink()
    except Exception:
        pass

    if returncode != 0:
        # Download failed or was killed — clean up any partial mp3 file
        logger.error(f"Download failed for {youtube_video_id} (exit code {returncode})")
        if error_output:
            logger.error(f"yt-dlp output: {error_output}")
        if audio_path.exists():
            try:
                audio_path.unlink()
                logger.info(f"Cleaned up partial file: {audio_path}")
            except Exception:
                pass
    else:
        # Success — verify the file exists
        if audio_path.exists():
            file_size = audio_path.stat().st_size
            logger.info(
                f"Audio file downloaded: {audio_path} ({file_size / 1024 / 1024:.2f} MB)"
            )

            # Clean up old audio files to maintain cache limit
            try:
                from services.cache import get_audio_cache

                audio_cache = get_audio_cache()
                audio_cache.cleanup_old_files()
            except Exception as e:
                logger.error(f"Error during audio cache cleanup: {e}")
        else:
            logger.error(
                f"Download completed (rc=0) but output file not found: {audio_path}"
            )

    # Always remove the marker file — download is no longer in progress
    try:
        if marker_path.exists():
            marker_path.unlink()
    except Exception:
        pass
