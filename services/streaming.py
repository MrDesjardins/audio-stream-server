"""
YouTube audio streaming service.

Handles yt-dlp and ffmpeg pipeline for streaming audio.
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
    Start yt-dlp -> ffmpeg pipeline to download and save audio file.

    Args:
        youtube_video_id: YouTube video ID
        skip_transcription: Whether to skip saving audio for transcription

    Returns:
        The ffmpeg process
    """
    audio_cache = get_audio_cache()
    audio_path = config.get_audio_path(youtube_video_id)

    # If audio file already exists in cache, no need to download again
    if audio_cache.check_file_exists(youtube_video_id):
        logger.info(f"Audio file for video {youtube_video_id} already exists in cache")
        return None

    logger.info(f"Downloading audio for video {youtube_video_id}")
    url = f"https://www.youtube.com/watch?v={youtube_video_id}"

    # Get best audio format (usually opus/vorbis in webm, or aac in m4a)
    # Use android player client to avoid JS runtime requirement
    yt_cmd = [
        "/usr/local/bin/yt-dlp",
        "-f",
        "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio",
        "--no-playlist",
        "--no-warnings",
        "--extractor-args",
        "youtube:player_client=android",
        "-o",
        "-",  # output to stdout
        url,
    ]

    # Build FFmpeg command - directly save to file (no stdout streaming needed)
    ffmpeg_cmd = [
        "ffmpeg",
        "-probesize",
        "10M",  # Analyze more data for better format detection
        "-analyzeduration",
        "10M",  # Analyze longer for accurate stream info
        "-err_detect",
        "ignore_err",  # Don't stop on minor errors
        "-fflags",
        "+genpts+igndts+discardcorrupt",  # Generate PTS, ignore DTS, discard corrupt packets
        "-thread_queue_size",
        "4096",  # Large input queue
        "-i",
        "pipe:0",  # Read from stdin
        "-map",
        "0:a",  # Map the audio stream
        "-c:a",
        "libmp3lame",  # MP3 encoder
        "-q:a",
        "2",  # VBR quality 2 (high quality, ~170-210 kbps)
        "-ar",
        "48000",  # Sample rate
        "-ac",
        "2",  # Stereo
        "-async",
        "1",  # Audio sync method
        "-y",  # Overwrite output file
        audio_path,  # Output directly to file
    ]

    # Start the download pipeline
    yt_proc = subprocess.Popen(yt_cmd, stdout=subprocess.PIPE, bufsize=64 * 1024 * 1024)
    ffmpeg_proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=yt_proc.stdout,
        stdout=subprocess.DEVNULL,  # No stdout output needed
        stderr=subprocess.DEVNULL,  # Suppress ffmpeg output
        bufsize=64 * 1024 * 1024
    )
    yt_proc.stdout.close()

    logger.info(f"Started downloading audio for video {youtube_video_id} to {audio_path}")

    # Wait for download to complete
    ffmpeg_proc.wait()
    yt_proc.wait()

    # Log the final file size
    if os.path.exists(audio_path):
        file_size = os.path.getsize(audio_path)
        logger.info(
            f"Audio file downloaded: {audio_path} ({file_size / 1024 / 1024:.2f} MB)"
        )
    else:
        logger.error(f"Failed to download audio file for {youtube_video_id}")

    return ffmpeg_proc
