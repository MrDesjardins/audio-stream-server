"""Tests for API client initialization."""

from unittest.mock import Mock, patch
from services.api_clients import get_openai_client, get_httpx_client


class TestGetOpenAIClient:
    """Tests for get_openai_client function."""

    @patch("services.api_clients.OpenAI")
    @patch("services.api_clients.get_config")
    def test_returns_cached_client_on_second_call(self, mock_config, mock_openai_class):
        """Test that client is cached and reused."""
        # Setup
        config = Mock()
        config.openai_api_key = "test-key"
        mock_config.return_value = config

        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        # First call creates client
        client1 = get_openai_client()

        # Second call returns cached client
        client2 = get_openai_client()

        # Verify
        assert client1 is client2
        # Check that OpenAI was called with at least the api_key
        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["api_key"] == "test-key"
        assert mock_openai_class.call_count == 1

    @patch("services.api_clients.OpenAI")
    @patch("services.api_clients.get_config")
    def test_creates_client_with_api_key(self, mock_config, mock_openai_class):
        """Test that client is created with correct API key."""
        # Setup
        config = Mock()
        config.openai_api_key = "my-secret-key"
        mock_config.return_value = config

        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        # Execute
        # Reset the cache first
        import services.api_clients

        services.api_clients._openai_client = None

        client = get_openai_client()

        # Verify
        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["api_key"] == "my-secret-key"
        assert mock_openai_class.call_count == 1
        assert client is mock_client


class TestGetHttpxClient:
    """Tests for get_httpx_client function."""

    @patch("services.api_clients.httpx.Client")
    def test_returns_cached_client_on_second_call(self, mock_httpx_class):
        """Test that httpx client is cached and reused."""
        # Reset the cache first
        import services.api_clients

        services.api_clients._httpx_client = None

        # Setup
        mock_client = Mock()
        mock_httpx_class.return_value = mock_client

        # First call creates client
        client1 = get_httpx_client()

        # Second call returns cached client
        client2 = get_httpx_client()

        # Verify
        assert client1 is client2
        # Check that httpx.Client was called with at least timeout
        call_kwargs = mock_httpx_class.call_args[1]
        assert call_kwargs["timeout"] == 30.0
        assert mock_httpx_class.call_count == 1

    @patch("services.api_clients.httpx.Client")
    def test_creates_client_with_timeout(self, mock_httpx_class):
        """Test that httpx client is created with correct timeout."""
        # Setup
        mock_client = Mock()
        mock_httpx_class.return_value = mock_client

        # Reset the cache first
        import services.api_clients

        services.api_clients._httpx_client = None

        # Execute
        client = get_httpx_client()

        # Verify
        call_kwargs = mock_httpx_class.call_args[1]
        assert call_kwargs["timeout"] == 30.0
        assert mock_httpx_class.call_count == 1
        assert client is mock_client
