"""Audio transcription using OpenAI Whisper API, Google Gemini, or Mistral AI."""

import logging
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Optional

import httpx
from google import genai
from google.genai.types import HttpOptions

from config import get_config
from services.database import log_llm_usage
from services.llm_clients import (
    get_tracked_openai_client,
    get_tracked_gemini_client,
    get_tracked_mistral_client,
)
from services.path_utils import expand_path, expand_path_str

logger = logging.getLogger(__name__)

# API Limitations
WHISPER_MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB file size limit
VOXTRAL_MAX_DURATION_SECONDS = 30 * 60  # 30 minutes duration limit
GEMINI_INLINE_MAX_FILE_SIZE = (
    20 * 1024 * 1024
)  # 20MB inline upload limit (use Files API for larger)


def get_audio_duration(audio_path: str) -> float:
    """
    Get audio duration in seconds using ffprobe.

    Args:
        audio_path: Path to the audio file

    Returns:
        Duration in seconds

    Raises:
        Exception: If duration cannot be determined
    """
    expanded_path = expand_path_str(audio_path)

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                expanded_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            raise Exception(f"ffprobe failed: {result.stderr}")

        duration = float(result.stdout.strip())
        return duration

    except (ValueError, subprocess.TimeoutExpired) as e:
        raise Exception(f"Failed to get audio duration: {e}")


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
    # Expand ~ in path for ffmpeg (ffmpeg doesn't handle ~ paths)
    expanded_audio_path = expand_path_str(audio_path)

    logger.info(
        f"Compressing audio file {expanded_audio_path} for Whisper (1.5x speed, saves API costs)"
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
            expanded_audio_path,
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

        temp_path_path = Path(temp_path)
        compressed_size = temp_path_path.stat().st_size
        original_size = Path(expanded_audio_path).stat().st_size

        logger.info(
            f"Compressed audio from {original_size / 1024 / 1024:.2f}MB "
            f"to {compressed_size / 1024 / 1024:.2f}MB (1.5x speed, mono, 32kbps)"
        )

        if compressed_size > WHISPER_MAX_FILE_SIZE:
            os.unlink(temp_path)
            duration_estimate = (
                original_size / 1024 / 1024
            ) / 1.2  # Rough estimate: ~1.2MB per minute
            raise Exception(
                f"Audio file too large for Whisper API:\n"
                f"  - Compressed size: {compressed_size / 1024 / 1024:.2f}MB\n"
                f"  - Whisper limit: {WHISPER_MAX_FILE_SIZE / 1024 / 1024:.0f}MB\n"
                f"  - Estimated duration: ~{duration_estimate:.0f} minutes\n"
                f"Suggestions:\n"
                f"  - Use Gemini (no file size limit, free tier available)\n"
                f"  - Split video into shorter segments\n"
                f"  - Use a different transcription provider"
            )

        return temp_path

    except Exception:
        # Clean up temp file on error
        temp_file = Path(temp_path)
        if temp_file.exists():
            temp_file.unlink()
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

    client = get_tracked_openai_client()

    # Always compress audio to save costs and reduce upload time
    file_size = expand_path(audio_path).stat().st_size
    file_size_mb = file_size / 1024 / 1024

    logger.info(
        f"Audio file size: {file_size_mb:.2f}MB - "
        f"compressing for Whisper (saves 33% API costs)"
    )

    # Warn if file is extremely large (compression may not be enough)
    # Typical compression ratio is 10:1, so 250MB original → ~25MB compressed
    if file_size > 250 * 1024 * 1024:  # 250MB
        logger.warning(
            f"Audio file is very large ({file_size_mb:.2f}MB). "
            f"Even with compression, it may exceed Whisper's 25MB limit. "
            f"Consider using Gemini or splitting the audio."
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

                # Extract video_id from audio_path for tracking
                video_id = None
                try:
                    # audio_path format: /path/to/{video_id}.mp3
                    video_id = Path(audio_path).stem
                except Exception:
                    pass

                # Get metadata for tracking
                audio_file_size = Path(file_to_transcribe).stat().st_size

                # Try to get precise duration using ffprobe
                audio_duration_seconds = None
                try:
                    ffprobe_result = subprocess.run(
                        [
                            "ffprobe",
                            "-v",
                            "error",
                            "-show_entries",
                            "format=duration",
                            "-of",
                            "default=noprint_wrappers=1:nokey=1",
                            file_to_transcribe,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if ffprobe_result.returncode == 0:
                        audio_duration_seconds = float(ffprobe_result.stdout.strip())
                except Exception:
                    pass

                metadata = {
                    "audio_file_size_bytes": audio_file_size,
                    "audio_duration_seconds": audio_duration_seconds,
                    "compressed": True,
                }

                with open(file_to_transcribe, "rb") as audio_file:
                    transcript = client.transcribe_audio(
                        audio_file,
                        feature="transcription",
                        video_id=video_id,
                        metadata=metadata,
                    )

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
        if compressed_path:
            compressed_path_path = Path(compressed_path)
            if compressed_path_path.exists():
                try:
                    compressed_path_path.unlink()
                    logger.info(f"Cleaned up compressed file: {compressed_path}")
                except Exception as e:
                    logger.warning(
                        f"Failed to clean up compressed file {compressed_path}: {e}"
                    )


def _transcribe_gemini_with_files_api(
    audio_path: str,
    config,
    audio_file_size: int,
    video_id: Optional[str] = None,
) -> str:
    """
    Transcribe audio using Gemini Files API (for files >20MB).

    Args:
        audio_path: Path to the audio file
        config: Application configuration
        audio_file_size: Size of the audio file in bytes
        video_id: Optional video ID for tracking

    Returns:
        The transcribed text

    Raises:
        Exception: If transcription fails
    """
    logger.info(
        f"Uploading audio file to Gemini Files API ({audio_file_size / 1024 / 1024:.2f}MB)"
    )

    # Configure longer timeout for large file uploads and transcription (10 minutes)
    timeout_config = httpx.Timeout(600.0, connect=60.0)
    httpx_client = httpx.Client(timeout=timeout_config)

    http_options = HttpOptions(httpx_client=httpx_client)
    client = genai.Client(api_key=config.gemini_api_key, http_options=http_options)

    # Upload file to Gemini Files API
    uploaded_file = client.files.upload(file=audio_path)

    if not uploaded_file.name:
        raise ValueError("File upload failed: no file name returned")

    logger.info(f"File uploaded successfully: {uploaded_file.name}")

    # Get audio duration for per-minute cost tracking
    audio_duration_seconds = None
    try:
        ffprobe_result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if ffprobe_result.returncode == 0:
            audio_duration_seconds = float(ffprobe_result.stdout.strip())
    except Exception as e:
        logger.warning(f"Failed to get audio duration: {e}")

    try:
        # Count tokens before transcription for accurate tracking
        prompt_tokens = None
        try:
            token_count_response = client.models.count_tokens(
                model=config.transcription_model,
                contents=[
                    "Please transcribe this audio file. Provide only the transcription text, no additional commentary.",
                    uploaded_file,
                ],
            )
            prompt_tokens = token_count_response.total_tokens
            logger.info(
                f"Gemini audio token count for {video_id}: {prompt_tokens} tokens (Files API)"
            )
        except Exception as e:
            logger.warning(f"Failed to count Gemini audio tokens (Files API): {e}")

        # Generate transcription using the uploaded file
        response = client.models.generate_content(
            model=config.transcription_model,
            contents=[
                "Please transcribe this audio file. Provide only the transcription text, no additional commentary.",
                uploaded_file,
            ],
        )

        transcript = response.text
        if not transcript:
            raise ValueError("Gemini returned empty transcript")

        # Track usage
        try:
            tracking_metadata = {
                "audio_file_size_bytes": audio_file_size,
                "transcript_length_chars": len(transcript),
                "upload_method": "files_api",
            }

            # Extract response token count from usage_metadata
            response_tokens = None

            if hasattr(response, "usage_metadata"):
                usage = response.usage_metadata
                # Use counted tokens for prompt if available, otherwise fall back to usage_metadata
                if prompt_tokens is None:
                    prompt_tokens = getattr(usage, "prompt_token_count", None)
                response_tokens = getattr(usage, "candidates_token_count", None)

            log_llm_usage(
                provider="gemini",
                model=config.transcription_model,
                feature="transcription",
                prompt_tokens=prompt_tokens,
                response_tokens=response_tokens,
                video_id=video_id,
                metadata=tracking_metadata,
                audio_duration_seconds=audio_duration_seconds,
            )
        except Exception as e:
            logger.warning(f"Failed to track Gemini Files API usage: {e}")

        return transcript

    finally:
        # Clean up uploaded file
        if uploaded_file.name:
            try:
                client.files.delete(name=uploaded_file.name)
                logger.info(f"Deleted uploaded file: {uploaded_file.name}")
            except Exception as e:
                logger.warning(
                    f"Failed to delete uploaded file {uploaded_file.name}: {e}"
                )


def transcribe_audio_gemini(audio_path: str, retries: int = 3) -> str:
    """
    Transcribe audio file using Google Gemini API.

    Gemini can process audio directly without compression/speed-up tricks.
    Uses Gemini 1.5 Flash which supports audio input.

    Automatically switches between inline upload (≤20MB) and Files API (>20MB).

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

    # Expand ~ in path (Python's open() doesn't handle ~ paths)
    expanded_audio_path = expand_path_str(audio_path)

    # Get audio file size to determine upload method
    audio_file_size = Path(expanded_audio_path).stat().st_size
    use_files_api = audio_file_size > GEMINI_INLINE_MAX_FILE_SIZE

    logger.info(
        f"Audio file size: {audio_file_size / 1024 / 1024:.2f}MB - "
        f"using {'Files API' if use_files_api else 'inline upload'} for Gemini"
    )

    # Extract video_id from audio_path for tracking
    video_id = None
    try:
        video_id = Path(audio_path).stem
    except Exception:
        pass

    last_error = None

    for attempt in range(retries):
        try:
            logger.info(
                f"Transcribing audio file with Gemini: {expanded_audio_path} (attempt {attempt + 1}/{retries})"
            )

            if use_files_api:
                # Use Files API for large files (>20MB)
                transcript = _transcribe_gemini_with_files_api(
                    expanded_audio_path,
                    config,
                    audio_file_size,
                    video_id,
                )
            else:
                # Use inline upload for small files (≤20MB)
                client = get_tracked_gemini_client()

                # Read audio file
                with open(expanded_audio_path, "rb") as audio_file:
                    audio_data = audio_file.read()

                # Get audio duration for per-minute cost tracking
                audio_duration_seconds = None
                try:
                    ffprobe_result = subprocess.run(
                        [
                            "ffprobe",
                            "-v",
                            "error",
                            "-show_entries",
                            "format=duration",
                            "-of",
                            "default=noprint_wrappers=1:nokey=1",
                            expanded_audio_path,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if ffprobe_result.returncode == 0:
                        audio_duration_seconds = float(ffprobe_result.stdout.strip())
                except Exception as e:
                    logger.warning(f"Failed to get audio duration: {e}")

                metadata = {
                    "audio_file_size_bytes": audio_file_size,
                    "audio_duration_seconds": audio_duration_seconds,
                }

                transcript = client.transcribe_audio(
                    audio_data,
                    mime_type="audio/mpeg",
                    feature="transcription",
                    video_id=video_id,
                    metadata=metadata,
                )

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


def transcribe_audio_mistral(audio_path: str, retries: int = 3) -> str:
    """
    Transcribe audio file using Mistral AI Voxtral API.

    Mistral AI's Voxtral models can process audio directly.
    Uses voxtral-mini-latest or configured model for transcription.

    Args:
        audio_path: Path to the audio file to transcribe
        retries: Number of retry attempts on failure

    Returns:
        The transcribed text

    Raises:
        Exception: If transcription fails after all retries
    """
    config = get_config()

    if not config.mistral_api_key:
        raise ValueError("Mistral API key not configured")

    client = get_tracked_mistral_client()

    # Expand ~ in path (Python's open() doesn't handle ~ paths)
    expanded_audio_path = expand_path_str(audio_path)

    # Check audio duration before attempting transcription (Voxtral has 15 min limit)
    audio_duration_seconds = None
    try:
        duration_seconds = get_audio_duration(audio_path)
        audio_duration_seconds = duration_seconds  # Store for tracking
        duration_minutes = duration_seconds / 60

        logger.info(
            f"Audio duration: {duration_minutes:.1f} minutes "
            f"(Voxtral limit: {VOXTRAL_MAX_DURATION_SECONDS / 60:.0f} minutes)"
        )

        if duration_seconds > VOXTRAL_MAX_DURATION_SECONDS:
            raise ValueError(
                f"Audio duration ({duration_minutes:.1f} minutes) exceeds Voxtral's "
                f"{VOXTRAL_MAX_DURATION_SECONDS / 60:.0f}-minute limit. "
                f"Please use a shorter audio file or switch to a different transcription provider."
            )
    except ValueError:
        # Re-raise duration limit errors
        raise
    except Exception as e:
        # Log warning but continue if duration check fails
        logger.warning(f"Failed to check audio duration: {e}. Continuing anyway...")

    last_error = None

    for attempt in range(retries):
        try:
            logger.info(
                f"Transcribing audio file with Mistral: {expanded_audio_path} (attempt {attempt + 1}/{retries})"
            )

            # Extract video_id from audio_path for tracking
            video_id = None
            try:
                video_id = Path(audio_path).stem
            except Exception:
                pass

            # Get audio file size for tracking
            audio_file_size = Path(expanded_audio_path).stat().st_size

            metadata = {
                "audio_file_size_bytes": audio_file_size,
                "audio_duration_seconds": audio_duration_seconds,
            }

            # Open and read audio file
            with open(expanded_audio_path, "rb") as audio_file:
                # Extract filename from path
                file_name = Path(expanded_audio_path).name

                transcript = client.transcribe_audio(
                    audio_file,
                    file_name=file_name,
                    feature="transcription",
                    video_id=video_id,
                    metadata=metadata,
                )

            logger.info(
                f"Successfully transcribed audio with Mistral ({len(transcript)} characters)"
            )

            return transcript

        except Exception as e:
            last_error = e
            logger.warning(f"Mistral transcription attempt {attempt + 1} failed: {e}")

            if attempt < retries - 1:
                # Exponential backoff
                wait_time = 2**attempt
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"All transcription attempts failed for {audio_path}")

    raise Exception(
        f"Mistral transcription failed after {retries} attempts: {last_error}"
    )


def transcribe_audio(audio_path: str, retries: int = 3) -> str:
    """
    Transcribe audio file using the configured provider.

    Routes to OpenAI Whisper, Google Gemini, or Mistral AI based on configuration.

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
    elif config.transcription_provider == "mistral":
        return transcribe_audio_mistral(audio_path, retries)
    else:
        raise ValueError(
            f"Invalid transcription provider: {config.transcription_provider}. "
            f"Valid options: 'openai', 'gemini', 'mistral'"
        )
