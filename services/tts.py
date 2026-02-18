"""
Text-to-Speech service supporting multiple providers (OpenAI, ElevenLabs).

Handles audio generation from text and file management.
"""

import re
import logging
from typing import Optional, Literal, List
from elevenlabs.client import ElevenLabs
from bs4 import BeautifulSoup

from services.path_utils import expand_path
from services.llm_clients import get_tracked_openai_client
from services.database import log_llm_usage

logger = logging.getLogger(__name__)

TTSProvider = Literal["openai", "elevenlabs"]


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


def _split_text_into_chunks(text: str, max_chars: int) -> List[str]:
    """
    Split text into chunks at sentence/paragraph boundaries, each under max_chars.

    Splits preferably at paragraph breaks (double newline), then sentence ends
    (. ! ?). If a single sentence still exceeds max_chars, it is split at the
    last space before the limit.

    Args:
        text: Text to split
        max_chars: Maximum characters per chunk

    Returns:
        List of text chunks, each at most max_chars characters
    """
    if len(text) <= max_chars:
        return [text]

    # Split on sentence-ending punctuation followed by spaces, or paragraph breaks.
    # The lookbehind keeps the punctuation attached to the preceding sentence.
    parts = re.split(r"(?<=[.!?]) +|\n\n", text)

    chunks: List[str] = []
    current_chunk = ""

    for part in parts:
        part = part.strip()
        if not part:
            continue

        candidate = (current_chunk + " " + part).strip() if current_chunk else part

        if len(candidate) <= max_chars:
            current_chunk = candidate
        else:
            # Flush the accumulated chunk
            if current_chunk:
                chunks.append(current_chunk)

            # If the part itself is too long, hard-split at word boundaries
            while len(part) > max_chars:
                split_at = part.rfind(" ", 0, max_chars)
                if split_at == -1:
                    split_at = max_chars
                chunks.append(part[:split_at])
                part = part[split_at:].lstrip()

            current_chunk = part

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _generate_audio_openai(
    text: str,
    voice: str,
    model: str = "tts-1",
    feature: str = "tts",
    video_id: Optional[str] = None,
) -> bytes:
    """
    Generate audio using OpenAI TTS API with usage tracking.

    Args:
        text: Text to convert to speech
        voice: OpenAI voice (alloy, echo, fable, onyx, nova, shimmer)
        model: Model to use (tts-1 or tts-1-hd)
        feature: Feature name for tracking (default: "tts")
        video_id: Associated video ID for tracking (optional)

    Returns:
        MP3 audio data as bytes

    Raises:
        TTSAPIError: If API request fails

    Note:
        OpenAI TTS has a 4096 character limit per request.
        Longer text is split into chunks at sentence boundaries and the
        resulting audio bytes are concatenated into a single MP3 stream.
    """
    max_chars = 4096
    chunks = _split_text_into_chunks(text, max_chars)

    if len(chunks) > 1:
        logger.info(
            f"Text split into {len(chunks)} chunks for OpenAI TTS ({len(text)} chars total)"
        )

    client = get_tracked_openai_client()
    audio_parts: List[bytes] = []

    for chunk in chunks:
        try:
            response = client.text_to_speech(
                text=chunk,
                voice=voice,
                model=model,
                feature=feature,
                video_id=video_id,
            )
            audio_parts.append(response.read())

        except Exception as e:
            error_msg = str(e)

            if "401" in error_msg or "unauthorized" in error_msg.lower():
                raise TTSAPIError("Invalid OpenAI API key")
            elif "429" in error_msg or "rate" in error_msg.lower():
                raise TTSAPIError(f"Rate limited: {error_msg}")
            elif "insufficient_quota" in error_msg.lower():
                raise TTSAPIError(f"Insufficient quota: {error_msg}")
            else:
                raise TTSAPIError(f"OpenAI TTS failed: {error_msg}")

    return b"".join(audio_parts)


def _generate_audio_elevenlabs(
    text: str,
    voice_id: str,
    api_key: str,
    model_id: str = "eleven_flash_v2_5",
    output_format: str = "mp3_44100_128",
    feature: str = "tts",
    video_id: Optional[str] = None,
) -> bytes:
    """
    Generate audio using ElevenLabs API with usage tracking.

    Args:
        text: Text to convert to speech
        voice_id: ElevenLabs voice ID
        api_key: ElevenLabs API key
        model_id: Model to use for generation
        output_format: Audio format
        feature: Feature name for tracking (default: "tts")
        video_id: Associated video ID for tracking (optional)

    Returns:
        MP3 audio data as bytes

    Raises:
        TTSAPIError: If API request fails

    Note:
        Character limits by model:
        - eleven_multilingual_v2: 10,000 chars
        - eleven_turbo_v2_5: 40,000 chars
        - eleven_flash_v2_5: 40,000 chars
    """
    model_limits = {
        "eleven_multilingual_v2": 10000,
        "eleven_turbo_v2_5": 40000,
        "eleven_flash_v2_5": 40000,
        "eleven_monolingual_v1": 5000,
    }
    max_chars = model_limits.get(model_id, 10000)
    chunks = _split_text_into_chunks(text, max_chars)

    if len(chunks) > 1:
        logger.info(
            f"Text split into {len(chunks)} chunks for ElevenLabs TTS ({len(text)} chars total)"
        )

    client = ElevenLabs(api_key=api_key)
    audio_parts: List[bytes] = []
    total_chars = 0

    for chunk in chunks:
        try:
            audio_generator = client.text_to_speech.convert(
                text=chunk,
                voice_id=voice_id,
                model_id=model_id,
                output_format=output_format,
            )
            audio_parts.append(b"".join(audio_generator))
            total_chars += len(chunk)

        except Exception as e:
            error_msg = str(e)

            if "quota_exceeded" in error_msg.lower():
                raise TTSAPIError(f"Quota exceeded: {error_msg}")
            elif "401" in error_msg or "unauthorized" in error_msg.lower():
                raise TTSAPIError("Invalid ElevenLabs API key")
            elif "402" in error_msg or "payment_required" in error_msg.lower():
                raise TTSAPIError(f"Payment required: {error_msg}")
            elif "429" in error_msg or "rate" in error_msg.lower():
                raise TTSAPIError(f"Rate limited: {error_msg}")
            else:
                raise TTSAPIError(f"ElevenLabs TTS failed: {error_msg}")

    # Track usage - ElevenLabs TTS priced per character
    try:
        metadata = {
            "character_count": total_chars,
            "voice_id": voice_id,
            "output_format": output_format,
        }

        log_llm_usage(
            provider="elevenlabs",
            model=model_id,
            feature=feature,
            prompt_tokens=total_chars,  # Store character count in prompt_tokens
            response_tokens=0,  # TTS doesn't have response tokens
            video_id=video_id,
            metadata=metadata,
        )
        logger.info(
            f"ElevenLabs TTS {model_id} call tracked for {feature} ({total_chars} chars)"
        )
    except Exception as e:
        logger.warning(f"Failed to track ElevenLabs TTS usage: {e}")

    return b"".join(audio_parts)


def generate_audio(
    text: str,
    api_key: Optional[str] = None,
    provider: TTSProvider = "openai",
    voice: Optional[str] = None,
    model: Optional[str] = None,
    feature: str = "tts",
    video_id: Optional[str] = None,
) -> bytes:
    """
    Generate audio from text using the specified TTS provider.

    Args:
        text: Text to convert to speech
        api_key: API key for the provider (required for ElevenLabs, optional for OpenAI)
        provider: TTS provider to use ("openai" or "elevenlabs")
        voice: Voice ID/name (provider-specific)
        model: Model ID (provider-specific)
        feature: Feature name for usage tracking (default: "tts")
        video_id: Associated video ID for tracking (optional)

    Returns:
        MP3 audio data as bytes

    Raises:
        TTSAPIError: If API request fails
        ValueError: If provider is invalid or required parameters are missing

    Provider-specific defaults:
        OpenAI:
            - voice: "alloy" (options: alloy, echo, fable, onyx, nova, shimmer)
            - model: "tts-1" (options: tts-1, tts-1-hd)
            - api_key: Read from config (automatic tracking)
        ElevenLabs:
            - voice: Must be provided
            - model: "eleven_flash_v2_5"
            - api_key: Required
    """
    if provider == "openai":
        voice = voice or "alloy"
        model = model or "tts-1"
        return _generate_audio_openai(text, voice, model, feature, video_id)

    elif provider == "elevenlabs":
        if not api_key:
            raise ValueError("ElevenLabs requires api_key parameter")
        if not voice:
            raise ValueError("ElevenLabs requires a voice_id")
        model = model or "eleven_flash_v2_5"
        return _generate_audio_elevenlabs(
            text, voice, api_key, model, feature=feature, video_id=video_id
        )

    else:
        raise ValueError(f"Unsupported TTS provider: {provider}")


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
    path = expand_path(file_path)

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
    path = expand_path(file_path)
    if not path.exists():
        return None

    # Estimate from file size (128kbps MP3 ≈ 16KB/s)
    file_size = path.stat().st_size
    return file_size // 16000
