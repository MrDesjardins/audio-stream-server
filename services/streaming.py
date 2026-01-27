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

        # Get best audio format (usually opus/vorbis in webm, or aac in m4a)
        # Don't use --extract-audio or --audio-format with stdout - just get raw stream
        yt_cmd = [
            "/usr/local/bin/yt-dlp",
            "-f",
            "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio",
            "--no-playlist",
            "--no-warnings",
            "-o",
            "-",  # output to stdout
            url,
        ]

        # If transcription is enabled and not skipped, save audio to file while streaming
        if config.transcription_enabled and not skip_transcription:
            logger.info(f"Saving audio to {audio_path} while streaming")

            # Use tee to write to both stdout and file
            # Increase buffer sizes to prevent glitches
            ffmpeg_cmd = [
                "ffmpeg",
                "-err_detect",
                "ignore_err",  # Don't stop on minor errors
                "-fflags",
                "+genpts+igndts",  # Generate PTS, ignore DTS issues
                "-thread_queue_size",
                "1024",  # Increase input queue size
                "-i",
                "pipe:0",
                "-map",
                "0:a",  # Map the audio stream
                "-c:a",
                "libmp3lame",  # MP3 encoder
                "-b:a",
                "192k",  # Constant bitrate for consistent quality
                "-ar",
                "48000",  # Sample rate
                "-ac",
                "2",  # Stereo
                "-bufsize",
                "2048k",  # Larger buffer to prevent underruns
                "-f",
                "tee",
                f"[f=mp3]pipe:1|[f=mp3]{audio_path}",
            ]
        else:
            # Standard streaming without saving
            # Use consistent encoding settings for quality
            ffmpeg_cmd = [
                "ffmpeg",
                "-err_detect",
                "ignore_err",  # Don't stop on minor errors
                "-fflags",
                "+genpts+igndts",  # Generate PTS, ignore DTS issues
                "-thread_queue_size",
                "1024",  # Increase input queue size
                "-i",
                "pipe:0",
                "-c:a",
                "libmp3lame",  # MP3 encoder
                "-b:a",
                "192k",  # Constant bitrate
                "-ar",
                "48000",  # Sample rate
                "-ac",
                "2",  # Stereo
                "-bufsize",
                "2048k",  # Larger buffer
                "-f",
                "mp3",
                "pipe:1",
            ]

        # Use larger pipe buffers (64MB) to prevent stuttering
        yt_proc = subprocess.Popen(yt_cmd, stdout=subprocess.PIPE, bufsize=64 * 1024 * 1024)
        ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd, stdin=yt_proc.stdout, stdout=subprocess.PIPE, bufsize=64 * 1024 * 1024
        )
        yt_proc.stdout.close()

    else:
        logger.info(
            f"Audio file for video {youtube_video_id} already in cache, streaming from cache"
        )
        # Stream the cached file with large buffer for smooth playback
        ffmpeg_cmd = [
            "ffmpeg",
            "-re",  # Read at native frame rate (prevents overwhelming client)
            "-i",
            audio_path,
            "-c:a",
            "copy",  # Just copy, don't re-encode
            "-f",
            "mp3",
            "pipe:1",
        ]
        ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, bufsize=64 * 1024 * 1024)

    # Start broadcasting to clients
    # The broadcaster will monitor the process and stop automatically when it completes
    broadcaster.start_broadcasting(ffmpeg_proc)

    logger.info(f"Started streaming audio for video {youtube_video_id}")

    # Log the final file size if transcription is enabled and not skipped
    if config.transcription_enabled and not skip_transcription and os.path.exists(audio_path):
        file_size = os.path.getsize(audio_path)
        logger.info(
            f"Audio file saved: {audio_path} ({file_size / 1024 / 1024:.2f} MB) - transcription job already queued"
        )

    return ffmpeg_proc
