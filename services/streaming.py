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


def start_youtube_download(youtube_video_id: str, skip_transcription: bool):
    """
    Download audio from YouTube and save as MP3 using yt-dlp.

    Uses yt-dlp's built-in audio extraction (--extract-audio) to download
    and convert directly to MP3. No ffmpeg pipe needed.

    Args:
        youtube_video_id: YouTube video ID
        skip_transcription: Whether to skip saving audio for transcription (unused, kept for API compat)

    Returns:
        The subprocess if successful, None otherwise
    """
    audio_cache = get_audio_cache()
    audio_path = config.get_audio_path(youtube_video_id)

    # If audio file already exists in cache, no need to download again
    if audio_cache.check_file_exists(youtube_video_id):
        logger.info(f"Audio file for video {youtube_video_id} already exists in cache")
        return None

    logger.info(f"Downloading audio for video {youtube_video_id}")
    url = f"https://www.youtube.com/watch?v={youtube_video_id}"

    # Use yt-dlp to download and convert directly to MP3.
    # --extract-audio handles the conversion internally (calls ffmpeg under the hood).
    # This avoids pipe-based yt-dlp | ffmpeg pipelines which can deadlock.
    stderr_path = audio_path + ".err"
    yt_cmd = [
        "/usr/local/bin/yt-dlp",
        "-f",
        "bestaudio/best",
        "--extract-audio",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "2",  # VBR quality 2 (high quality, ~170-210 kbps)
        "--no-playlist",
        "--extractor-args",
        "youtube:player_client=android",
        "-o",
        audio_path,  # Output directly to target path
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

        # Wait for download to complete
        proc.wait()

        # Check for errors
        if proc.returncode != 0:
            error_output = ""
            try:
                with open(stderr_path, "r") as f:
                    error_output = f.read()[-500:]
            except Exception:
                pass
            logger.error(f"yt-dlp failed for {youtube_video_id} (exit code {proc.returncode})")
            logger.error(f"yt-dlp output: {error_output}")
            # Clean up partial file if it exists
            if os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except Exception:
                    pass
            return None

        # Verify file was created
        if os.path.exists(audio_path):
            file_size = os.path.getsize(audio_path)
            logger.info(
                f"Audio file downloaded: {audio_path} ({file_size / 1024 / 1024:.2f} MB)"
            )
            return proc
        else:
            logger.error(f"Download completed but file not found: {audio_path}")
            return None

    except Exception as e:
        logger.error(f"Exception during download for {youtube_video_id}: {e}")
        # Clean up partial file if it exists
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception:
                pass
        return None
    finally:
        # Clean up stderr log file
        try:
            if os.path.exists(stderr_path):
                os.remove(stderr_path)
        except Exception:
            pass
