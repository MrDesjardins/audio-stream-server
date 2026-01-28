"""Configuration management for audio stream server with transcription."""

import os
from typing import Optional
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    # Server settings
    fastapi_host: str
    fastapi_port: int

    # Transcription settings
    transcription_enabled: bool
    openai_api_key: Optional[str]
    temp_audio_dir: str
    max_audio_length_minutes: int

    # Summarization settings
    summary_provider: str  # "openai" or "gemini"
    gemini_api_key: Optional[str]

    # Trilium settings
    trilium_url: Optional[str]
    trilium_etapi_token: Optional[str]
    trilium_parent_note_id: Optional[str]

    # Book-based audiobook suggestions
    book_suggestions_enabled: bool
    books_to_analyze: int
    suggestions_count: int
    suggestions_ai_provider: str  # "openai" or "gemini"

    @classmethod
    def load_from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        transcription_enabled = os.getenv("TRANSCRIPTION_ENABLED", "false").lower() == "true"

        config = cls(
            # Server settings
            fastapi_host=os.getenv("FASTAPI_HOST", "127.0.0.1"),
            fastapi_port=int(os.getenv("FASTAPI_API_PORT", "8000")),
            # Transcription settings
            transcription_enabled=transcription_enabled,
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            temp_audio_dir=os.getenv("TEMP_AUDIO_DIR", "/tmp/audio-transcriptions"),
            max_audio_length_minutes=int(os.getenv("MAX_AUDIO_LENGTH_MINUTES", "60")),
            # Summarization settings
            summary_provider=os.getenv("SUMMARY_PROVIDER", "openai").lower(),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            # Trilium settings
            trilium_url=os.getenv("TRILIUM_URL", "").rstrip("/") or None,
            trilium_etapi_token=os.getenv("TRILIUM_ETAPI_TOKEN"),
            trilium_parent_note_id=os.getenv("TRILIUM_PARENT_NOTE_ID"),
            # Book suggestions settings
            book_suggestions_enabled=os.getenv("BOOK_SUGGESTIONS_ENABLED", "false").lower()
            == "true",
            books_to_analyze=int(os.getenv("BOOKS_TO_ANALYZE", "10")),
            suggestions_count=int(os.getenv("SUGGESTIONS_COUNT", "4")),
            suggestions_ai_provider=os.getenv("SUGGESTIONS_AI_PROVIDER", "openai").lower(),
        )

        # Validate configuration if transcription is enabled
        if transcription_enabled:
            config.validate()

        # Validate book suggestions if enabled
        if config.book_suggestions_enabled:
            config.validate_book_suggestions()

        return config

    def validate(self) -> None:
        """Validate that required configuration is present."""
        errors = []

        # Check OpenAI API key
        if not self.openai_api_key:
            errors.append("OPENAI_API_KEY is required when TRANSCRIPTION_ENABLED=true")

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

        # Check Trilium configuration
        if not self.trilium_url:
            errors.append("TRILIUM_URL is required when TRANSCRIPTION_ENABLED=true")
        if not self.trilium_etapi_token:
            errors.append("TRILIUM_ETAPI_TOKEN is required when TRANSCRIPTION_ENABLED=true")
        if not self.trilium_parent_note_id:
            errors.append("TRILIUM_PARENT_NOTE_ID is required when TRANSCRIPTION_ENABLED=true")

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
            errors.append("TRILIUM_ETAPI_TOKEN is required when BOOK_SUGGESTIONS_ENABLED=true")
        if not self.trilium_parent_note_id:
            errors.append(
                "TRILIUM_PARENT_NOTE_ID is required when BOOK_SUGGESTIONS_ENABLED=true (used to find recent audiobook summaries)"
            )

        # Check AI provider configuration
        if self.suggestions_ai_provider == "openai":
            if not self.openai_api_key:
                errors.append("OPENAI_API_KEY is required when SUGGESTIONS_AI_PROVIDER=openai")
        elif self.suggestions_ai_provider == "gemini":
            if not self.gemini_api_key:
                errors.append("GEMINI_API_KEY is required when SUGGESTIONS_AI_PROVIDER=gemini")
        else:
            errors.append(
                f"Invalid SUGGESTIONS_AI_PROVIDER: {self.suggestions_ai_provider}. Must be 'openai' or 'gemini'"
            )

        if errors:
            error_msg = "Book suggestions configuration validation failed:\n  - " + "\n  - ".join(
                errors
            )
            raise ValueError(error_msg)

    def get_audio_path(self, video_id: str) -> str:
        """Get the path for storing audio file for a video."""
        return os.path.join(self.temp_audio_dir, f"{video_id}.mp3")


# Global config instance
config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global config
    if config is None:
        config = Config.load_from_env()
    return config
