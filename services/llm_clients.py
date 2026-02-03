"""
LLM client wrappers with automatic usage tracking.

These wrappers ensure that:
1. Model names are always in sync between client usage and tracking
2. Token usage is automatically logged without manual calls
3. All LLM API calls are consistently tracked
"""

import logging
from typing import Optional, Any, Dict
from config import get_config
from services.database import log_llm_usage

logger = logging.getLogger(__name__)


class TrackedOpenAIClient:
    """
    Wrapper for OpenAI client that automatically tracks usage.

    This ensures the model names used in API calls match what's logged
    to the database, avoiding synchronization issues.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize OpenAI client wrapper.

        Args:
            api_key: OpenAI API key (optional, uses config if not provided)
        """
        from services.api_clients import get_openai_client

        self.config = get_config()
        self.client = get_openai_client()

        # Model configurations - single source of truth
        self.whisper_model = (
            self.config.transcription_model
        )  # From config (whisper-1, etc.)
        self.chat_model = self.config.summary_model  # From config (gpt-4o-mini, etc.)

    def transcribe_audio(
        self,
        audio_file,
        feature: str = "transcription",
        video_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> str:
        """
        Transcribe audio with automatic usage tracking.

        Args:
            audio_file: Audio file object (opened in binary mode)
            feature: Feature name for tracking (default: "transcription")
            video_id: Associated video ID (optional)
            metadata: Additional metadata (optional)

        Returns:
            Transcribed text
        """
        try:
            # Make API call with configured model
            response = self.client.audio.transcriptions.create(
                model=self.whisper_model, file=audio_file, response_format="text"
            )

            transcript = response if isinstance(response, str) else response.text

            # Track usage (Whisper doesn't return token counts)
            try:
                tracking_metadata = metadata or {}
                tracking_metadata["transcript_length_chars"] = len(transcript)

                log_llm_usage(
                    provider="openai",
                    model=self.whisper_model,  # Always matches what was used
                    feature=feature,
                    video_id=video_id,
                    metadata=tracking_metadata,
                )
            except Exception as e:
                logger.warning(f"Failed to track Whisper usage: {e}")

            return transcript

        except Exception:
            # Don't catch API errors, let them propagate
            raise

    def create_chat_completion(
        self,
        messages: list,
        feature: str,
        video_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model_override: Optional[str] = None,
    ) -> Any:
        """
        Create chat completion with automatic usage tracking.

        Args:
            messages: List of message dicts for the chat
            feature: Feature name for tracking (e.g., "summarization", "weekly_summary")
            video_id: Associated video ID (optional)
            metadata: Additional metadata (optional)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            model_override: Override the default chat model (optional)

        Returns:
            OpenAI response object
        """
        try:
            model_to_use = model_override or self.chat_model

            # Make API call
            response = self.client.chat.completions.create(
                model=model_to_use,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            # Track usage
            try:
                tracking_metadata = metadata or {}

                # Extract content length
                if response.choices and response.choices[0].message.content:
                    tracking_metadata["response_length_chars"] = len(
                        response.choices[0].message.content
                    )

                log_llm_usage(
                    provider="openai",
                    model=model_to_use,  # Always matches what was used
                    feature=feature,
                    prompt_tokens=response.usage.prompt_tokens
                    if response.usage
                    else None,
                    response_tokens=response.usage.completion_tokens
                    if response.usage
                    else None,
                    video_id=video_id,
                    metadata=tracking_metadata,
                )
            except Exception as e:
                logger.warning(f"Failed to track OpenAI chat usage: {e}")

            return response

        except Exception:
            raise


class TrackedGeminiClient:
    """
    Wrapper for Gemini client that automatically tracks usage.

    This ensures the model names used in API calls match what's logged
    to the database, avoiding synchronization issues.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Gemini client wrapper.

        Args:
            api_key: Gemini API key (optional, uses config if not provided)
        """
        from google import genai

        self.config = get_config()
        self.genai = genai

        # Get API key
        self.api_key = api_key or self.config.gemini_api_key
        if not self.api_key:
            raise ValueError("Gemini API key not configured")

        # Model configurations - single source of truth
        self.transcription_model = (
            self.config.transcription_model
        )  # From config (gemini-2.5-flash-preview-tts, etc.)
        self.chat_model = (
            self.config.summary_model
        )  # From config (gemini-1.5-flash, etc.)

    def transcribe_audio(
        self,
        audio_data: bytes,
        mime_type: str = "audio/mpeg",
        feature: str = "transcription",
        video_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> str:
        """
        Transcribe audio with automatic usage tracking.

        Args:
            audio_data: Audio file bytes
            mime_type: MIME type of audio (default: "audio/mpeg")
            feature: Feature name for tracking (default: "transcription")
            video_id: Associated video ID (optional)
            metadata: Additional metadata (optional)

        Returns:
            Transcribed text
        """
        try:
            client = self.genai.Client(api_key=self.api_key)

            # Make API call with configured model
            response = client.models.generate_content(
                model=self.transcription_model,
                contents=[
                    {
                        "parts": [
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
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

            # Track usage
            try:
                tracking_metadata = metadata or {}
                tracking_metadata["transcript_length_chars"] = len(transcript)

                # Extract token counts if available
                prompt_tokens = None
                response_tokens = None

                if hasattr(response, "usage_metadata"):
                    usage = response.usage_metadata
                    prompt_tokens = getattr(usage, "prompt_token_count", None)
                    response_tokens = getattr(usage, "candidates_token_count", None)

                log_llm_usage(
                    provider="gemini",
                    model=self.transcription_model,  # Always matches what was used
                    feature=feature,
                    prompt_tokens=prompt_tokens,
                    response_tokens=response_tokens,
                    video_id=video_id,
                    metadata=tracking_metadata,
                )
            except Exception as e:
                logger.warning(f"Failed to track Gemini transcription usage: {e}")

            return transcript

        except Exception:
            raise

    def generate_content(
        self,
        prompt: str,
        feature: str,
        video_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        model_override: Optional[str] = None,
    ) -> Any:
        """
        Generate content with automatic usage tracking.

        Args:
            prompt: Text prompt
            feature: Feature name for tracking (e.g., "summarization", "book_suggestions")
            video_id: Associated video ID (optional)
            metadata: Additional metadata (optional)
            model_override: Override the default chat model (optional)

        Returns:
            Gemini response object
        """
        try:
            client = self.genai.Client(api_key=self.api_key)
            model_to_use = model_override or self.chat_model

            # Make API call
            response = client.models.generate_content(
                model=model_to_use,
                contents=prompt,
            )

            # Track usage
            try:
                tracking_metadata = metadata or {}

                if response.text:
                    tracking_metadata["response_length_chars"] = len(response.text)

                # Extract token counts if available
                prompt_tokens = None
                response_tokens = None

                if hasattr(response, "usage_metadata"):
                    usage = response.usage_metadata
                    prompt_tokens = getattr(usage, "prompt_token_count", None)
                    response_tokens = getattr(usage, "candidates_token_count", None)

                log_llm_usage(
                    provider="gemini",
                    model=model_to_use,  # Always matches what was used
                    feature=feature,
                    prompt_tokens=prompt_tokens,
                    response_tokens=response_tokens,
                    video_id=video_id,
                    metadata=tracking_metadata,
                )
            except Exception as e:
                logger.warning(f"Failed to track Gemini usage: {e}")

            return response

        except Exception:
            raise


# Singleton instances (lazy initialization)
_openai_tracked_client = None
_gemini_tracked_client = None


def get_tracked_openai_client() -> TrackedOpenAIClient:
    """Get singleton tracked OpenAI client."""
    global _openai_tracked_client
    if _openai_tracked_client is None:
        _openai_tracked_client = TrackedOpenAIClient()
    return _openai_tracked_client


def get_tracked_gemini_client() -> TrackedGeminiClient:
    """Get singleton tracked Gemini client."""
    global _gemini_tracked_client
    if _gemini_tracked_client is None:
        _gemini_tracked_client = TrackedGeminiClient()
    return _gemini_tracked_client
