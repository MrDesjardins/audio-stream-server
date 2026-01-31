"""Singleton API client factories for connection pooling."""

import threading
import logging
from typing import Optional
from openai import OpenAI
import httpx

from config import get_config

logger = logging.getLogger(__name__)

# Global client instances
_openai_client: Optional[OpenAI] = None
_httpx_client: Optional[httpx.Client] = None
_client_lock = threading.Lock()


def get_openai_client() -> OpenAI:
    """
    Get the global OpenAI client instance.

    Creates a singleton client with connection pooling for better performance.
    """
    global _openai_client
    if _openai_client is None:
        with _client_lock:
            if _openai_client is None:
                config = get_config()
                _openai_client = OpenAI(
                    api_key=config.openai_api_key, timeout=60.0, max_retries=2
                )
                logger.info("Initialized OpenAI client with connection pooling")
    return _openai_client


def get_httpx_client() -> httpx.Client:
    """
    Get the global httpx client instance.

    Creates a singleton client with connection pooling for better performance.
    Configured with:
    - max_connections: 10 (total concurrent connections)
    - max_keepalive_connections: 5 (persistent connections to reuse)
    """
    global _httpx_client
    if _httpx_client is None:
        with _client_lock:
            if _httpx_client is None:
                _httpx_client = httpx.Client(
                    timeout=30.0,
                    limits=httpx.Limits(
                        max_connections=10, max_keepalive_connections=5
                    ),
                )
                logger.info("Initialized httpx client with connection pooling")
    return _httpx_client


def close_clients() -> None:
    """
    Close all client connections.

    Should be called on application shutdown.
    """
    global _openai_client, _httpx_client

    with _client_lock:
        if _httpx_client is not None:
            try:
                _httpx_client.close()
                logger.info("Closed httpx client")
            except Exception as e:
                logger.error(f"Error closing httpx client: {e}")
            finally:
                _httpx_client = None

        if _openai_client is not None:
            try:
                _openai_client.close()
                logger.info("Closed OpenAI client")
            except Exception as e:
                logger.error(f"Error closing OpenAI client: {e}")
            finally:
                _openai_client = None
