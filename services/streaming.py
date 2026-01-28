"""
YouTube audio download service.

Downloads audio from YouTube using yt-dlp and saves as MP3.
"""

import logging
import os
import subprocess
from services.cache import get_audio_cache
from config import get_config

logger = logging.getLogger(__name__)
config = get_config()


def _get_download_marker(youtube_video_id: str) -> str:
    """Get the path for the download-in-progress marker file."""
    return os.path.join(config.temp_audio_dir, f"{youtube_video_id}.downloading")


def is_download_in_progress(youtube_video_id: str) -> bool:
    """Check if a download is currently in progress for this video."""
    return os.path.exists(_get_download_marker(youtube_video_id))


def start_youtube_download(youtube_video_id: str, skip_transcription: bool):
    """
    Start downloading audio from YouTube. Returns the process immediately
    so the caller can store it and terminate if needed.

    Call finish_youtube_download() after proc.wait() to handle cleanup.

    Args:
        youtube_video_id: YouTube video ID
        skip_transcription: Unused, kept for API compatibility

    Returns:
        (proc, youtube_video_id) tuple if started, (None, video_id) if already cached or error
    """
    audio_cache = get_audio_cache()
    audio_path = config.get_audio_path(youtube_video_id)

    if audio_cache.check_file_exists(youtube_video_id):
        logger.info(f"Audio file for video {youtube_video_id} already exists in cache")
        return None, youtube_video_id

    logger.info(f"Downloading audio for video {youtube_video_id}")
    url = f"https://www.youtube.com/watch?v={youtube_video_id}"

    # Create marker file so the /audio endpoint won't serve a partial file
    marker_path = _get_download_marker(youtube_video_id)
    try:
        open(marker_path, "w").close()
    except Exception as e:
        logger.error(f"Failed to create download marker: {e}")

    stderr_path = audio_path + ".err"

    # Use yt-dlp to download and convert directly to MP3.
    # -o uses the base path WITHOUT extension — yt-dlp appends .mp3 via --audio-format.
    # Passing -o with .mp3 extension causes yt-dlp to create path.mp3.mp3.
    # --extract-audio handles the ffmpeg conversion internally.
    base_path = os.path.join(config.temp_audio_dir, youtube_video_id)
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

        logger.info(f"Started downloading audio for video {youtube_video_id} to {audio_path}")
        return proc, youtube_video_id

    except Exception as e:
        logger.error(f"Exception starting download for {youtube_video_id}: {e}")
        # Clean up marker on failure to start
        try:
            if os.path.exists(marker_path):
                os.remove(marker_path)
        except Exception:
            pass
        return None, youtube_video_id


def finish_youtube_download(youtube_video_id: str, returncode: int):
    """
    Handle post-download cleanup: remove marker file, log errors on failure.
    Call this after proc.wait() completes in the download thread.

    Args:
        youtube_video_id: YouTube video ID
        returncode: Process exit code (0 = success)
    """
    audio_path = config.get_audio_path(youtube_video_id)
    marker_path = _get_download_marker(youtube_video_id)
    stderr_path = audio_path + ".err"

    # Read stderr for error reporting
    error_output = ""
    try:
        with open(stderr_path, "r") as f:
            error_output = f.read()[-500:]
    except Exception:
        pass

    # Clean up stderr file
    try:
        if os.path.exists(stderr_path):
            os.remove(stderr_path)
    except Exception:
        pass

    if returncode != 0:
        # Download failed or was killed — clean up any partial mp3 file
        logger.error(f"Download failed for {youtube_video_id} (exit code {returncode})")
        if error_output:
            logger.error(f"yt-dlp output: {error_output}")
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
                logger.info(f"Cleaned up partial file: {audio_path}")
            except Exception:
                pass
    else:
        # Success — verify the file exists
        if os.path.exists(audio_path):
            file_size = os.path.getsize(audio_path)
            logger.info(
                f"Audio file downloaded: {audio_path} ({file_size / 1024 / 1024:.2f} MB)"
            )
        else:
            logger.error(f"Download completed (rc=0) but output file not found: {audio_path}")

    # Always remove the marker file — download is no longer in progress
    try:
        if os.path.exists(marker_path):
            os.remove(marker_path)
    except Exception:
        pass
