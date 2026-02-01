"""
Text-to-Speech service using ElevenLabs API.

Handles audio generation from text and file management.
"""

import re
from pathlib import Path
from typing import Optional
from elevenlabs.client import ElevenLabs
from bs4 import BeautifulSoup


class TTSError(Exception):
    """Base exception for TTS-related errors."""

    pass


class TTSAPIError(TTSError):
    """Error communicating with TTS API."""

    pass


class TTSTextTooLongError(TTSError):
    """Text exceeds maximum length for TTS."""

    pass


def extract_summary_text_for_tts(html_content: str) -> str:
    """
    Extract clean text from HTML summary for TTS.

    Removes:
    - "Books Read This Week" section (which appears at the beginning)
    - HTML tags
    - Excessive whitespace

    The weekly summary structure is:
    1. Books Read This Week (h3 + ul) <- Remove this
    2. Overview (h2) <- Start from here
    3. 15 Most Important Learnings (h2)
    4. Common Themes (h2)

    Args:
        html_content: HTML content from Trilium note

    Returns:
        Clean text suitable for TTS
    """
    # Parse HTML
    soup = BeautifulSoup(html_content, "html.parser")

    # Find the "Books Read This Week" heading
    books_heading = None
    for heading in soup.find_all(["h2", "h3", "h4"]):
        if "books read" in heading.get_text().lower():
            books_heading = heading
            break

    if books_heading:
        # Find all elements to remove (from start until the next h2)
        elements_to_remove = []

        # Add the books heading itself
        elements_to_remove.append(books_heading)

        # Add all siblings between books heading and the next h2 (Overview)
        for sibling in books_heading.find_next_siblings():
            # Stop when we hit the next major heading (Overview, etc.)
            if sibling.name == "h2":
                break
            elements_to_remove.append(sibling)

        # Remove all those elements
        for element in elements_to_remove:
            element.decompose()

    # Get text content
    text = soup.get_text()

    # Clean up whitespace
    text = re.sub(r"\n\s*\n+", "\n\n", text)  # Multiple newlines to double
    text = re.sub(r" +", " ", text)  # Multiple spaces to single
    text = text.strip()

    return text


def generate_audio(
    text: str,
    voice_id: str,
    api_key: str,
    model_id: str = "eleven_flash_v2_5",
    output_format: str = "mp3_44100_128",
) -> bytes:
    """
    Generate audio from text using ElevenLabs Python SDK.

    Args:
        text: Text to convert to speech
        voice_id: ElevenLabs voice ID
        api_key: ElevenLabs API key
        model_id: Model to use for generation (default: eleven_multilingual_v2)
        output_format: Audio format (default: mp3_44100_128)

    Returns:
        MP3 audio data as bytes

    Raises:
        TTSTextTooLongError: If text exceeds maximum length
        TTSAPIError: If API request fails

    Note:
        Character limits by model:
        - eleven_multilingual_v2: 10,000 chars
        - eleven_turbo_v2_5: 40,000 chars
        - eleven_flash_v2_5: 40,000 chars
    """
    # Get character limit based on model
    model_limits = {
        "eleven_multilingual_v2": 10000,
        "eleven_turbo_v2_5": 40000,
        "eleven_flash_v2_5": 40000,
        "eleven_monolingual_v1": 5000,
    }
    max_chars = model_limits.get(model_id, 10000)  # Default to multilingual v2 limit

    # Check text length and truncate if needed
    if len(text) > max_chars:
        # Truncate with ellipsis
        text = text[: max_chars - 3] + "..."

    try:
        # Initialize ElevenLabs client
        client = ElevenLabs(api_key=api_key)

        # Generate audio using SDK
        audio_generator = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=model_id,
            output_format=output_format,
        )

        # The SDK returns an iterator of audio chunks, collect them all
        audio_bytes = b"".join(audio_generator)

        return audio_bytes

    except Exception as e:
        # Parse error message for common issues
        error_msg = str(e)

        if "401" in error_msg or "unauthorized" in error_msg.lower():
            raise TTSAPIError("Invalid API key")
        elif "402" in error_msg or "payment_required" in error_msg.lower():
            raise TTSAPIError(f"Payment required: {error_msg}")
        elif "429" in error_msg or "rate" in error_msg.lower():
            raise TTSAPIError(f"Rate limited: {error_msg}")
        else:
            raise TTSAPIError(f"Failed to generate audio: {error_msg}")


def save_audio_file(audio_data: bytes, file_path: str) -> int:
    """
    Save audio data to file and calculate duration.

    Args:
        audio_data: MP3 audio bytes
        file_path: Path to save the file

    Returns:
        Duration in seconds (estimated from file size)

    Raises:
        IOError: If file cannot be written
    """
    path = Path(file_path).expanduser().resolve()

    # Create parent directory if needed
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write audio file
    path.write_bytes(audio_data)

    # Estimate duration from file size
    # MP3 at 128kbps ≈ 16KB per second
    duration_seconds = len(audio_data) // 16000

    return duration_seconds


def get_audio_duration(file_path: str) -> Optional[int]:
    """
    Get duration of an audio file in seconds.

    Uses file size estimation since we don't have mutagen dependency.

    Args:
        file_path: Path to audio file

    Returns:
        Duration in seconds, or None if file doesn't exist
    """
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return None

    # Estimate from file size (128kbps MP3 ≈ 16KB/s)
    file_size = path.stat().st_size
    return file_size // 16000
