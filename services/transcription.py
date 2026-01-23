"""Audio transcription using OpenAI Whisper API."""
import logging
import time
from typing import Optional
from openai import OpenAI

from config import get_config

logger = logging.getLogger(__name__)


def transcribe_audio(audio_path: str, retries: int = 3) -> str:
    """
    Transcribe audio file using OpenAI Whisper API.

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

    client = OpenAI(api_key=config.openai_api_key)

    last_error = None
    for attempt in range(retries):
        try:
            logger.info(f"Transcribing audio file: {audio_path} (attempt {attempt + 1}/{retries})")

            with open(audio_path, "rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text"
                )

            transcript = response if isinstance(response, str) else response.text
            logger.info(f"Successfully transcribed audio ({len(transcript)} characters)")
            return transcript

        except Exception as e:
            last_error = e
            logger.warning(f"Transcription attempt {attempt + 1} failed: {e}")

            if attempt < retries - 1:
                # Exponential backoff
                wait_time = 2 ** attempt
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"All transcription attempts failed for {audio_path}")

    raise Exception(f"Transcription failed after {retries} attempts: {last_error}")
