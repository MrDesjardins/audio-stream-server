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


def start_youtube_stream(youtube_video_id: str, skip_transcription: bool, broadcaster):
    """
    Start yt-dlp -> ffmpeg streaming to stdout (and optionally save to file).

    Args:
        youtube_video_id: YouTube video ID
        skip_transcription: Whether to skip saving audio for transcription
        broadcaster: StreamBroadcaster instance to handle multi-client streaming

    Returns:
        The ffmpeg process
    """
    audio_cache = get_audio_cache()
    audio_path = config.get_audio_path(youtube_video_id)

    # If audio file already exists in cache, stream from cache
    if not audio_cache.check_file_exists(youtube_video_id):
        url = f"https://www.youtube.com/watch?v={youtube_video_id}"
        yt_cmd = [
            "/usr/local/bin/yt-dlp",
            "-f",
            "bestaudio",
            "--extract-audio",
            "--audio-format", "mp3",
            "-o", "-",  # output to stdout
            url
        ]

        # If transcription is enabled and not skipped, save audio to file while streaming
        if config.transcription_enabled and not skip_transcription:
            logger.info(f"Saving audio to {audio_path} while streaming")

            # Use tee to write to both stdout and file
            ffmpeg_cmd = [
                "ffmpeg",
                "-i", "pipe:0",
                "-map", "0:a",          # Map the audio stream
                "-c:a", "libmp3lame",   # Explicitly specify MP3 encoder
                "-q:a", "2",            # Quality setting (0-9, lower is better)
                "-f", "tee",
                f"[f=mp3]pipe:1|[f=mp3]{audio_path}",
            ]
        else:
            # Standard streaming without saving
            ffmpeg_cmd = [
                "ffmpeg",
                "-i", "pipe:0",
                "-f", "mp3",
                "pipe:1",
            ]
        yt_proc = subprocess.Popen(yt_cmd, stdout=subprocess.PIPE)
        ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=yt_proc.stdout, stdout=subprocess.PIPE)
        yt_proc.stdout.close()

    else:
        logger.info(f"Audio file for video {youtube_video_id} already in cache, streaming from cache")
        # Stream the cached file
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", audio_path,
            "-f", "mp3",
            "pipe:1",
        ]
        ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE)

    # Start broadcasting to clients
    # The broadcaster will monitor the process and stop automatically when it completes
    broadcaster.start_broadcasting(ffmpeg_proc)

    logger.info(f"Started streaming audio for video {youtube_video_id}")

    # Log the final file size if transcription is enabled and not skipped
    if config.transcription_enabled and not skip_transcription and os.path.exists(audio_path):
        file_size = os.path.getsize(audio_path)
        logger.info(f"Audio file saved: {audio_path} ({file_size / 1024 / 1024:.2f} MB) - transcription job already queued")

    return ffmpeg_proc
