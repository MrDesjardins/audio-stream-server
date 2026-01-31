"""Audio transcription using OpenAI Whisper API or Google Gemini."""

import logging
import os
import subprocess
import tempfile
import time
from google import genai

from config import get_config
from services.api_clients import get_openai_client

logger = logging.getLogger(__name__)

# OpenAI Whisper API file size limit (25MB)
WHISPER_MAX_FILE_SIZE = 25 * 1024 * 1024


def compress_audio_for_whisper(audio_path: str) -> str:
    """
    Compress audio file for Whisper API transcription.

    Uses multiple techniques to reduce file size and API costs:
    - Convert to mono (50% reduction)
    - Lower bitrate to 32kbps (speech optimized)
    - Lower sample rate to 16kHz (sufficient for speech)
    - Speed up audio by 1.5x (33% cost reduction, Whisper handles this well)

    Args:
        audio_path: Path to the original audio file

    Returns:
        Path to the compressed audio file (temporary file)

    Raises:
        Exception: If compression fails
    """
    logger.info(
        f"Compressing audio file {audio_path} for Whisper (1.5x speed, saves API costs)"
    )

    # Create temporary file for compressed audio
    temp_fd, temp_path = tempfile.mkstemp(suffix=".mp3", prefix="whisper_compressed_")
    os.close(temp_fd)

    try:
        # Compress with lower bitrate and speed up audio to reduce file size
        # Using 32kbps mono at 1.5x speed - good enough for speech transcription
        # Whisper can handle sped-up audio very well
        compress_cmd = [
            "ffmpeg",
            "-i",
            audio_path,
            "-filter:a",
            "atempo=1.5",  # Speed up by 1.5x (33% file size reduction)
            "-map",
            "0:a",
            "-ac",
            "1",  # Convert to mono
            "-b:a",
            "32k",  # Low bitrate for small file size
            "-ar",
            "16000",  # Lower sample rate (16kHz is fine for speech)
            "-f",
            "mp3",
            "-y",  # Overwrite output file
            temp_path,
        ]

        result = subprocess.run(
            compress_cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if result.returncode != 0:
            raise Exception(f"ffmpeg compression failed: {result.stderr}")

        compressed_size = os.path.getsize(temp_path)
        original_size = os.path.getsize(audio_path)

        logger.info(
            f"Compressed audio from {original_size / 1024 / 1024:.2f}MB "
            f"to {compressed_size / 1024 / 1024:.2f}MB (1.5x speed, mono, 32kbps)"
        )

        if compressed_size > WHISPER_MAX_FILE_SIZE:
            os.unlink(temp_path)
            raise Exception(
                f"Compressed file ({compressed_size / 1024 / 1024:.2f}MB) "
                f"still exceeds Whisper limit ({WHISPER_MAX_FILE_SIZE / 1024 / 1024:.0f}MB). "
                f"Video is too long for transcription."
            )

        return temp_path

    except Exception:
        # Clean up temp file on error
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def transcribe_audio_openai(audio_path: str, retries: int = 3) -> str:
    """
    Transcribe audio file using OpenAI Whisper API.

    Always compresses audio before transcription to:
    - Save API costs (33% reduction with 1.5x speed)
    - Reduce upload time
    - Ensure files stay under 25MB limit

    Args:
        audio_path: Path to the audio file to transcribe
        retries: Number of retry attempts on failure

    Returns:
        The transcribed text

    Raises:
        Exception: If transcription fails after all retries
    """
    config = get_config()

    if not config.openai_api_key:
        raise ValueError("OpenAI API key not configured")

    client = get_openai_client()

    # Always compress audio to save costs and reduce upload time
    file_size = os.path.getsize(audio_path)
    logger.info(
        f"Audio file size: {file_size / 1024 / 1024:.2f}MB - "
        f"compressing for Whisper (saves 33% API costs)"
    )

    compressed_path = None
    file_to_transcribe = audio_path

    try:
        compressed_path = compress_audio_for_whisper(audio_path)
        file_to_transcribe = compressed_path
    except Exception as e:
        logger.error(f"Failed to compress audio: {e}")
        raise Exception(f"Audio compression failed: {e}")

    last_error = None
    try:
        for attempt in range(retries):
            try:
                logger.info(
                    f"Transcribing audio file: {file_to_transcribe} (attempt {attempt + 1}/{retries})"
                )

                with open(file_to_transcribe, "rb") as audio_file:
                    response = client.audio.transcriptions.create(
                        model="whisper-1", file=audio_file, response_format="text"
                    )

                transcript = response if isinstance(response, str) else response.text
                logger.info(
                    f"Successfully transcribed audio ({len(transcript)} characters)"
                )
                return transcript

            except Exception as e:
                last_error = e
                logger.warning(f"Transcription attempt {attempt + 1} failed: {e}")

                if attempt < retries - 1:
                    # Exponential backoff
                    wait_time = 2**attempt
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logger.error(
                        f"All transcription attempts failed for {file_to_transcribe}"
                    )

        raise Exception(f"Transcription failed after {retries} attempts: {last_error}")

    finally:
        # Clean up compressed file if it was created
        if compressed_path and os.path.exists(compressed_path):
            try:
                os.unlink(compressed_path)
                logger.info(f"Cleaned up compressed file: {compressed_path}")
            except Exception as e:
                logger.warning(
                    f"Failed to clean up compressed file {compressed_path}: {e}"
                )


def transcribe_audio_gemini(audio_path: str, retries: int = 3) -> str:
    """
    Transcribe audio file using Google Gemini API.

    Gemini can process audio directly without compression/speed-up tricks.
    Uses Gemini 1.5 Flash which supports audio input.

    Args:
        audio_path: Path to the audio file to transcribe
        retries: Number of retry attempts on failure

    Returns:
        The transcribed text

    Raises:
        Exception: If transcription fails after all retries
    """
    config = get_config()

    if not config.gemini_api_key:
        raise ValueError("Gemini API key not configured")

    last_error = None

    for attempt in range(retries):
        try:
            logger.info(
                f"Transcribing audio file with Gemini: {audio_path} (attempt {attempt + 1}/{retries})"
            )

            # Create Gemini client
            client = genai.Client(api_key=config.gemini_api_key)

            # Upload the audio file
            with open(audio_path, "rb") as audio_file:
                audio_data = audio_file.read()

            # Use Gemini to transcribe
            # Gemini 1.5 Flash supports audio input
            response = client.models.generate_content(
                model="gemini-1.5-flash",
                contents=[
                    {
                        "parts": [
                            {
                                "inline_data": {
                                    "mime_type": "audio/mpeg",
                                    "data": audio_data,
                                }
                            },
                            {
                                "text": "Please transcribe this audio file. Provide only the transcription text, no additional commentary."
                            },
                        ]
                    }
                ],
            )

            transcript = response.text
            logger.info(
                f"Successfully transcribed audio with Gemini ({len(transcript)} characters)"
            )
            return transcript

        except Exception as e:
            last_error = e
            logger.warning(f"Gemini transcription attempt {attempt + 1} failed: {e}")

            if attempt < retries - 1:
                # Exponential backoff
                wait_time = 2**attempt
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"All transcription attempts failed for {audio_path}")

    raise Exception(
        f"Gemini transcription failed after {retries} attempts: {last_error}"
    )


def transcribe_audio(audio_path: str, retries: int = 3) -> str:
    """
    Transcribe audio file using the configured provider.

    Routes to either OpenAI Whisper or Google Gemini based on configuration.

    Args:
        audio_path: Path to the audio file to transcribe
        retries: Number of retry attempts on failure

    Returns:
        The transcribed text

    Raises:
        Exception: If transcription fails or provider is invalid
    """
    config = get_config()

    if config.transcription_provider == "openai":
        return transcribe_audio_openai(audio_path, retries)
    elif config.transcription_provider == "gemini":
        return transcribe_audio_gemini(audio_path, retries)
    else:
        raise ValueError(
            f"Invalid transcription provider: {config.transcription_provider}"
        )
