"""Shared helpers for LLM fallback behavior."""

from typing import Optional

from config import Config

OPENAI_FALLBACK_MODEL = "gpt-4o-mini"


def has_openai_api_key(config: Optional[Config]) -> bool:
    """Return True when OpenAI fallback can be attempted."""
    return bool(config and config.openai_api_key and config.openai_api_key.strip())
