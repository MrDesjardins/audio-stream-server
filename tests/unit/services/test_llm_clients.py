"""Tests for LLM client wrappers."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.llm_clients import TrackedGeminiClient


class RetryableGeminiError(Exception):
    """Test error that matches google.genai.errors.ServerError shape."""

    status_code = 503


class TestTrackedGeminiClient:
    """Tests for TrackedGeminiClient."""

    @patch("services.llm_clients.log_llm_usage")
    @patch("services.llm_clients.time.sleep")
    def test_generate_content_retries_retryable_gemini_error(
        self, mock_sleep, mock_log_llm_usage
    ):
        """Gemini text generation should retry transient 5xx failures."""
        response = SimpleNamespace(text="Recovered summary", usage_metadata=None)
        models = Mock()
        models.generate_content.side_effect = [
            RetryableGeminiError("503 UNAVAILABLE"),
            response,
        ]
        sdk_client = SimpleNamespace(models=models)

        client = TrackedGeminiClient.__new__(TrackedGeminiClient)
        client.api_key = "test-key"
        client.chat_model = "gemini-2.5-flash"
        client.genai = SimpleNamespace(Client=Mock(return_value=sdk_client))

        result = client.generate_content(
            prompt="Summarize this",
            feature="summarization",
            video_id="v3XiO_9VVSU",
        )

        assert result is response
        assert models.generate_content.call_count == 2
        mock_sleep.assert_called_once_with(15)
        mock_log_llm_usage.assert_called_once()
