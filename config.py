"""Configuration management for audio stream server with transcription."""

import os
import threading
import logging
from typing import Optional, Literal, cast
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)


def _parse_int(
    value: str,
    default: int,
    min_val: Optional[int] = None,
    max_val: Optional[int] = None,
) -> int:
    """
    Parse integer from string with validation and bounds checking.

    Args:
        value: String value to parse
        default: Default value if parsing fails
        min_val: Minimum allowed value (inclusive)
        max_val: Maximum allowed value (inclusive)

    Returns:
        Parsed integer value or default if parsing fails or out of bounds
    """
    try:
        result = int(value)
        if min_val is not None and result < min_val:
            logger.warning(
                f"Value {result} below minimum {min_val}, using default {default}"
            )
            return default
        if max_val is not None and result > max_val:
            logger.warning(
                f"Value {result} above maximum {max_val}, using default {default}"
            )
            return default
        return result
    except (ValueError, TypeError):
        logger.warning(f"Invalid integer value '{value}', using default {default}")
        return default


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    # Server settings
    fastapi_host: str
    fastapi_port: int

    # Audio settings
    # 2 = ~170 kbps (~76 MB/hr)
    # 3 = ~160 kbps (~72 MB/hr)
    # 4 = ~128 kbps (~58 MB per hour)
    # 5 = ~112 kbps (~50 MB/hr)
    # 6 = ~96 kbps  (~43 MB/hr)
    # 7 = ~80 kbps  (~36 MB/hr)
    audio_quality: int  # VBR quality 0-9 (lower = higher quality, 4 = ~128kbps)
    prefetch_threshold_seconds: (
        int  # Seconds before end to start pre-downloading next track
    )

    # Transcription settings
    transcription_enabled: bool
    transcription_provider: str  # "openai", "gemini", or "mistral"
    transcription_model: str  # Model name for transcription
    openai_api_key: Optional[str]
    mistral_api_key: Optional[str]
    temp_audio_dir: str
    max_audio_length_minutes: int

    # Summarization settings
    summary_provider: str  # "openai" or "gemini"
    summary_model: str  # Model name for video summarization
    gemini_api_key: Optional[str]

    # Weekly summary settings (separate from video summarization)
    weekly_summary_provider: str  # "openai" or "gemini"
    weekly_summary_model: str  # Model name for weekly summaries

    # Trilium settings
    trilium_url: Optional[str]
    trilium_etapi_token: Optional[str]
    trilium_parent_note_id: Optional[str]

    # Book-based audiobook suggestions
    book_suggestions_enabled: bool
    books_to_analyze: int
    suggestions_count: int
    suggestions_ai_provider: str  # "openai" or "gemini"
    suggestions_model: str  # Model name for suggestions

    # Weekly summary settings
    weekly_summary_enabled: bool

    # TTS settings
    tts_enabled: bool
    tts_provider: Literal["openai", "elevenlabs"]
    openai_tts_voice: str  # OpenAI voice (alloy, echo, fable, onyx, nova, shimmer)
    openai_tts_model: str  # OpenAI model (tts-1 or tts-1-hd)
    elevenlabs_api_key: Optional[str]
    elevenlabs_voice_id: str
    elevenlabs_model_id: str
    weekly_summary_audio_dir: str

    # Client-side logging settings
    client_log_batch_interval: int  # Milliseconds between log batches

    @classmethod
    def load_from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        transcription_enabled = (
            os.getenv("TRANSCRIPTION_ENABLED", "false").lower() == "true"
        )

        # Get providers first to determine defaults
        # Gemini for everything except Whisper transcription
        transcription_provider = os.getenv("TRANSCRIPTION_PROVIDER", "openai").lower()
        summary_provider = os.getenv("SUMMARY_PROVIDER", "gemini").lower()
        weekly_summary_provider = os.getenv("WEEKLY_SUMMARY_PROVIDER", "gemini").lower()
        suggestions_ai_provider = os.getenv("SUGGESTIONS_AI_PROVIDER", "gemini").lower()

        # Determine default models based on providers
        if transcription_provider == "openai":
            default_transcription_model = "whisper-1"
        elif transcription_provider == "mistral":
            default_transcription_model = "voxtral-mini-latest"
        else:  # gemini
            default_transcription_model = "gemini-2.5-flash-lite"
        default_summary_model = (
            "gpt-4o-mini" if summary_provider == "openai" else "gemini-2.5-flash"
        )
        default_weekly_summary_model = (
            "gpt-4o-mini" if weekly_summary_provider == "openai" else "gemini-2.5-flash"
        )
        default_suggestions_model = (
            "gpt-4o-mini" if suggestions_ai_provider == "openai" else "gemini-2.5-flash"
        )

        config = cls(
            # Server settings
            fastapi_host=os.getenv("FASTAPI_HOST", "127.0.0.1"),
            fastapi_port=_parse_int(
                os.getenv("FASTAPI_API_PORT", "8000"), 8000, 1, 65535
            ),
            # Audio settings
            audio_quality=_parse_int(os.getenv("AUDIO_QUALITY", "4"), 4, 0, 9),
            prefetch_threshold_seconds=_parse_int(
                os.getenv("PREFETCH_THRESHOLD_SECONDS", "30"), 30, 0, 300
            ),
            # Transcription settings
            transcription_enabled=transcription_enabled,
            transcription_provider=transcription_provider,
            transcription_model=os.getenv(
                "TRANSCRIPTION_MODEL", default_transcription_model
            ),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            mistral_api_key=os.getenv("MISTRAL_API_KEY"),
            temp_audio_dir=os.getenv("TEMP_AUDIO_DIR", "/tmp/audio-transcriptions"),
            max_audio_length_minutes=_parse_int(
                os.getenv("MAX_AUDIO_LENGTH_MINUTES", "60"), 60, 1, 600
            ),
            # Summarization settings
            summary_provider=summary_provider,
            summary_model=os.getenv("SUMMARY_MODEL", default_summary_model),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            # Weekly summary settings
            weekly_summary_provider=weekly_summary_provider,
            weekly_summary_model=os.getenv(
                "WEEKLY_SUMMARY_MODEL", default_weekly_summary_model
            ),
            # Trilium settings
            trilium_url=os.getenv("TRILIUM_URL", "").rstrip("/") or None,
            trilium_etapi_token=os.getenv("TRILIUM_ETAPI_TOKEN"),
            trilium_parent_note_id=os.getenv("TRILIUM_PARENT_NOTE_ID"),
            # Book suggestions settings
            book_suggestions_enabled=os.getenv(
                "BOOK_SUGGESTIONS_ENABLED", "false"
            ).lower()
            == "true",
            books_to_analyze=_parse_int(
                os.getenv("BOOKS_TO_ANALYZE", "10"), 10, 1, 100
            ),
            suggestions_count=_parse_int(os.getenv("SUGGESTIONS_COUNT", "4"), 4, 1, 20),
            suggestions_ai_provider=suggestions_ai_provider,
            suggestions_model=os.getenv("SUGGESTIONS_MODEL", default_suggestions_model),
            # Weekly summary settings
            weekly_summary_enabled=os.getenv("WEEKLY_SUMMARY_ENABLED", "false").lower()
            == "true",
            # TTS settings
            tts_enabled=os.getenv("TTS_ENABLED", "false").lower() == "true",
            tts_provider=cast(
                Literal["openai", "elevenlabs"],
                os.getenv("TTS_PROVIDER", "openai").lower(),
            ),
            openai_tts_voice=os.getenv("OPENAI_TTS_VOICE", "alloy"),
            openai_tts_model=os.getenv("OPENAI_TTS_MODEL", "tts-1"),
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY"),
            elevenlabs_voice_id=os.getenv(
                "ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB"
            ),  # Adam - free voice
            elevenlabs_model_id=os.getenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5"),
            weekly_summary_audio_dir=os.getenv(
                "WEEKLY_SUMMARY_AUDIO_DIR", "/var/audio-summaries"
            ),
            # Client-side logging settings
            client_log_batch_interval=_parse_int(
                os.getenv("CLIENT_LOG_BATCH_INTERVAL", "5000"), 5000, 1000, 60000
            ),  # 1-60 seconds
        )

        # Validate configuration if transcription is enabled
        if transcription_enabled:
            config.validate()

        # Validate book suggestions if enabled
        if config.book_suggestions_enabled:
            config.validate_book_suggestions()

        # Validate TTS if enabled
        if config.tts_enabled:
            config.validate_tts()

        return config

    def validate(self) -> None:
        """Validate that required configuration is present."""
        errors = []

        # Check transcription provider configuration
        if self.transcription_provider == "openai":
            if not self.openai_api_key:
                errors.append(
                    "OPENAI_API_KEY is required when TRANSCRIPTION_PROVIDER=openai"
                )
        elif self.transcription_provider == "gemini":
            if not self.gemini_api_key:
                errors.append(
                    "GEMINI_API_KEY is required when TRANSCRIPTION_PROVIDER=gemini"
                )
        else:
            errors.append(
                f"Invalid TRANSCRIPTION_PROVIDER: {self.transcription_provider}. Must be 'openai' or 'gemini'"
            )

        # Check summarization provider configuration
        if self.summary_provider == "openai":
            if not self.openai_api_key:
                errors.append("OPENAI_API_KEY is required when SUMMARY_PROVIDER=openai")
        elif self.summary_provider == "gemini":
            if not self.gemini_api_key:
                errors.append("GEMINI_API_KEY is required when SUMMARY_PROVIDER=gemini")
        else:
            errors.append(
                f"Invalid SUMMARY_PROVIDER: {self.summary_provider}. Must be 'openai' or 'gemini'"
            )

        # Check weekly summary provider configuration
        if self.weekly_summary_provider == "openai":
            if not self.openai_api_key:
                errors.append(
                    "OPENAI_API_KEY is required when WEEKLY_SUMMARY_PROVIDER=openai"
                )
        elif self.weekly_summary_provider == "gemini":
            if not self.gemini_api_key:
                errors.append(
                    "GEMINI_API_KEY is required when WEEKLY_SUMMARY_PROVIDER=gemini"
                )
        else:
            errors.append(
                f"Invalid WEEKLY_SUMMARY_PROVIDER: {self.weekly_summary_provider}. Must be 'openai' or 'gemini'"
            )

        # Check Trilium configuration
        if not self.trilium_url:
            errors.append("TRILIUM_URL is required when TRANSCRIPTION_ENABLED=true")
        if not self.trilium_etapi_token:
            errors.append(
                "TRILIUM_ETAPI_TOKEN is required when TRANSCRIPTION_ENABLED=true"
            )
        if not self.trilium_parent_note_id:
            errors.append(
                "TRILIUM_PARENT_NOTE_ID is required when TRANSCRIPTION_ENABLED=true"
            )

        if errors:
            error_msg = "Configuration validation failed:\n  - " + "\n  - ".join(errors)
            raise ValueError(error_msg)

    def validate_book_suggestions(self) -> None:
        """Validate that required configuration for book suggestions is present."""
        errors = []

        # Check Trilium configuration
        if not self.trilium_url:
            errors.append("TRILIUM_URL is required when BOOK_SUGGESTIONS_ENABLED=true")
        if not self.trilium_etapi_token:
            errors.append(
                "TRILIUM_ETAPI_TOKEN is required when BOOK_SUGGESTIONS_ENABLED=true"
            )
        if not self.trilium_parent_note_id:
            errors.append(
                "TRILIUM_PARENT_NOTE_ID is required when BOOK_SUGGESTIONS_ENABLED=true (used to find recent audiobook summaries)"
            )

        # Check AI provider configuration
        if self.suggestions_ai_provider == "openai":
            if not self.openai_api_key:
                errors.append(
                    "OPENAI_API_KEY is required when SUGGESTIONS_AI_PROVIDER=openai"
                )
        elif self.suggestions_ai_provider == "gemini":
            if not self.gemini_api_key:
                errors.append(
                    "GEMINI_API_KEY is required when SUGGESTIONS_AI_PROVIDER=gemini"
                )
        else:
            errors.append(
                f"Invalid SUGGESTIONS_AI_PROVIDER: {self.suggestions_ai_provider}. Must be 'openai' or 'gemini'"
            )

        if errors:
            error_msg = (
                "Book suggestions configuration validation failed:\n  - "
                + "\n  - ".join(errors)
            )
            raise ValueError(error_msg)

    def validate_tts(self) -> None:
        """Validate that required configuration for TTS is present."""
        errors = []

        # Validate TTS provider
        if self.tts_provider not in ["openai", "elevenlabs"]:
            errors.append(
                f"TTS_PROVIDER must be 'openai' or 'elevenlabs', got '{self.tts_provider}'"
            )

        # Validate provider-specific configuration
        if self.tts_provider == "openai":
            if not self.openai_api_key:
                errors.append("OPENAI_API_KEY is required when TTS_PROVIDER=openai")
        elif self.tts_provider == "elevenlabs":
            if not self.elevenlabs_api_key:
                errors.append(
                    "ELEVENLABS_API_KEY is required when TTS_PROVIDER=elevenlabs"
                )

        if errors:
            error_msg = "TTS configuration validation failed:\n  - " + "\n  - ".join(
                errors
            )
            raise ValueError(error_msg)

    def get_audio_path(self, video_id: str) -> str:
        """Get the path for storing audio file for a video."""
        return os.path.join(self.temp_audio_dir, f"{video_id}.mp3")

    def get_weekly_summary_audio_path(self, week_year: str) -> str:
        """Get the path for storing weekly summary audio file."""
        return os.path.join(self.weekly_summary_audio_dir, f"{week_year}.mp3")


# Global config instance
config: Optional[Config] = None
_config_lock = threading.Lock()


def get_config() -> Config:
    """Get the global configuration instance."""
    global config
    if config is None:
        with _config_lock:
            if config is None:
                config = Config.load_from_env()
    return config
