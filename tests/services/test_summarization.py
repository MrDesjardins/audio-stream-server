"""Tests for summarization service."""

from unittest.mock import Mock, patch
import pytest
from services.summarization import summarize_transcript, SUMMARY_PROMPT_TEMPLATE


class TestSummarizeTranscript:
    """Tests for summarize_transcript function."""

    @patch("services.summarization._summarize_with_openai")
    @patch("services.summarization.get_config")
    def test_summarize_transcript_with_openai(self, mock_config, mock_openai):
        """Test summarization with OpenAI provider."""
        config = Mock()
        config.summary_provider = "openai"
        mock_config.return_value = config

        mock_openai.return_value = "OpenAI summary"

        result = summarize_transcript("Test transcript", "test123")

        assert result == "OpenAI summary"
        mock_openai.assert_called_once_with("Test transcript", "test123")

    @patch("services.summarization._summarize_with_gemini")
    @patch("services.summarization.get_config")
    def test_summarize_transcript_with_gemini(self, mock_config, mock_gemini):
        """Test summarization with Gemini provider."""
        config = Mock()
        config.summary_provider = "gemini"
        mock_config.return_value = config

        mock_gemini.return_value = "Gemini summary"

        result = summarize_transcript("Test transcript", "test123")

        assert result == "Gemini summary"
        mock_gemini.assert_called_once_with("Test transcript", "test123")

    @patch("services.summarization.get_config")
    def test_summarize_transcript_unknown_provider(self, mock_config):
        """Test summarization with unknown provider."""
        config = Mock()
        config.summary_provider = "unknown"
        mock_config.return_value = config

        with pytest.raises(ValueError, match="Unknown summary provider"):
            summarize_transcript("Test transcript", "test123")


class TestSummarizeWithOpenAI:
    """Tests for OpenAI summarization."""

    @patch("services.summarization.get_config")
    def test_summarize_with_openai_no_api_key(self, mock_config):
        """Test OpenAI summarization without API key."""
        from services.summarization import _summarize_with_openai

        config = Mock()
        config.openai_api_key = None
        mock_config.return_value = config

        with pytest.raises(ValueError, match="OpenAI API key not configured"):
            _summarize_with_openai("Test transcript", "test123")

    @patch("services.summarization.get_tracked_openai_client")
    @patch("services.summarization.get_config")
    def test_summarize_with_openai_success(self, mock_config, mock_get_client):
        """Test successful OpenAI summarization."""
        from services.summarization import _summarize_with_openai

        config = Mock()
        config.openai_api_key = "test-key"
        mock_config.return_value = config

        # Mock OpenAI client and response
        mock_client = Mock()
        mock_response = Mock()
        mock_message = Mock()
        mock_message.content = "This is the summary"
        mock_choice = Mock()
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        mock_client.create_chat_completion.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = _summarize_with_openai("Test transcript", "test123")

        assert result == "This is the summary"

        # Verify API call
        mock_client.create_chat_completion.assert_called_once()
        call_args = mock_client.create_chat_completion.call_args
        assert call_args[1]["temperature"] == 0.7
        assert call_args[1]["max_tokens"] == 1200
        assert call_args[1]["feature"] == "summarization"
        assert call_args[1]["video_id"] == "test123"

        # Verify messages
        messages = call_args[1]["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "Test transcript" in messages[1]["content"]

    @patch("services.summarization.get_tracked_openai_client")
    @patch("services.summarization.get_config")
    def test_summarize_with_openai_api_error(self, mock_config, mock_get_client):
        """Test OpenAI summarization with API error."""
        from services.summarization import _summarize_with_openai

        config = Mock()
        config.openai_api_key = "test-key"
        mock_config.return_value = config

        mock_client = Mock()
        mock_client.create_chat_completion.side_effect = Exception("API error")
        mock_get_client.return_value = mock_client

        with pytest.raises(Exception, match="API error"):
            _summarize_with_openai("Test transcript", "test123")


class TestSummarizeWithGemini:
    """Tests for Gemini summarization."""

    @patch("services.summarization.get_config")
    def test_summarize_with_gemini_no_api_key(self, mock_config):
        """Test Gemini summarization without API key."""
        from services.summarization import _summarize_with_gemini

        config = Mock()
        config.gemini_api_key = None
        mock_config.return_value = config

        with pytest.raises(ValueError, match="Gemini API key not configured"):
            _summarize_with_gemini("Test transcript", "test123")

    @patch("services.summarization.get_tracked_gemini_client")
    @patch("services.summarization.get_config")
    def test_summarize_with_gemini_success(self, mock_config, mock_get_client):
        """Test successful Gemini summarization."""
        from services.summarization import _summarize_with_gemini

        config = Mock()
        config.gemini_api_key = "test-key"
        mock_config.return_value = config

        # Mock Gemini client and response
        mock_client = Mock()
        mock_response = Mock()
        mock_response.text = "This is the Gemini summary"
        mock_client.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = _summarize_with_gemini("Test transcript", "test123")

        assert result == "This is the Gemini summary"

        # Verify API call
        mock_client.generate_content.assert_called_once()
        call_args = mock_client.generate_content.call_args
        assert call_args[1]["feature"] == "summarization"
        assert call_args[1]["video_id"] == "test123"
        assert "Test transcript" in call_args[1]["prompt"]

    @patch("services.summarization.get_tracked_gemini_client")
    @patch("services.summarization.get_config")
    def test_summarize_with_gemini_api_error(self, mock_config, mock_get_client):
        """Test Gemini summarization with API error."""
        from services.summarization import _summarize_with_gemini

        config = Mock()
        config.gemini_api_key = "test-key"
        mock_config.return_value = config

        mock_client = Mock()
        mock_client.generate_content.side_effect = Exception("API error")
        mock_get_client.return_value = mock_client

        with pytest.raises(Exception, match="API error"):
            _summarize_with_gemini("Test transcript", "test123")


class TestSummaryPrompt:
    """Tests for summary prompt template."""

    def test_summary_prompt_template(self):
        """Test that prompt template contains expected elements."""
        assert "title" in SUMMARY_PROMPT_TEMPLATE.lower()
        assert "overview" in SUMMARY_PROMPT_TEMPLATE.lower()
        assert "key points" in SUMMARY_PROMPT_TEMPLATE.lower()
        assert "{transcript}" in SUMMARY_PROMPT_TEMPLATE

    def test_summary_prompt_formatting(self):
        """Test that prompt template can be formatted."""
        formatted = SUMMARY_PROMPT_TEMPLATE.format(transcript="Test content")
        assert "Test content" in formatted
        assert "{transcript}" not in formatted
