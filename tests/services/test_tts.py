"""Tests for TTS service."""

import pytest
from unittest.mock import Mock, patch

from services.tts import (
    extract_summary_text_for_tts,
    generate_audio,
    save_audio_file,
    get_audio_duration,
    TTSAPIError,
)


class TestExtractSummaryTextForTTS:
    """Tests for extract_summary_text_for_tts function."""

    def test_removes_books_section(self):
        """Should remove 'Books Read This Week' section at the beginning."""
        html = """
        <div>
            <h3>Books Read This Week</h3>
            <ul>
                <li>Book 1</li>
                <li>Book 2</li>
            </ul>
            <h2>Overview</h2>
            <p>This is the summary content.</p>
        </div>
        """
        result = extract_summary_text_for_tts(html)

        assert "This is the summary content" in result
        assert "Overview" in result
        assert "Books Read This Week" not in result
        assert "Book 1" not in result
        assert "Book 2" not in result

    def test_removes_html_tags(self):
        """Should strip HTML tags."""
        html = "<div><p>Hello <strong>world</strong>!</p></div>"
        result = extract_summary_text_for_tts(html)

        assert "<p>" not in result
        assert "<strong>" not in result
        assert "Hello world!" in result

    def test_cleans_whitespace(self):
        """Should clean up excessive whitespace."""
        html = "<p>Line 1</p>\n\n\n<p>Line 2</p>"
        result = extract_summary_text_for_tts(html)

        # Should normalize to double newlines
        assert result.count("\n\n") <= 1  # At most one double newline
        assert "Line 1" in result
        assert "Line 2" in result

    def test_empty_html(self):
        """Should handle empty HTML."""
        result = extract_summary_text_for_tts("")
        assert result == ""

    def test_case_insensitive_books_match(self):
        """Should match 'Books Read' case-insensitively."""
        html = """
        <h2>BOOKS READ THIS WEEK</h2>
        <ul><li>Book 1</li></ul>
        <h2>Overview</h2>
        <p>Summary text</p>
        """
        result = extract_summary_text_for_tts(html)

        assert "Summary text" in result
        assert "Overview" in result
        assert "BOOKS READ" not in result
        assert "Book 1" not in result


class TestGenerateAudio:
    """Tests for generate_audio function."""

    @patch("services.tts.ElevenLabs")
    def test_successful_generation(self, mock_elevenlabs_class):
        """Should generate audio successfully."""
        # Setup mock
        mock_client = Mock()
        mock_tts = Mock()

        # Mock the audio generator (returns iterator of bytes)
        mock_tts.convert.return_value = [b"fake ", b"audio ", b"data"]
        mock_client.text_to_speech = mock_tts
        mock_elevenlabs_class.return_value = mock_client

        # Call function
        result = generate_audio(
            text="Hello world",
            voice_id="test-voice-id",
            api_key="test-api-key",
        )

        # Assertions
        assert result == b"fake audio data"
        mock_elevenlabs_class.assert_called_once_with(api_key="test-api-key")
        mock_tts.convert.assert_called_once()

        # Check parameters
        call_kwargs = mock_tts.convert.call_args.kwargs
        assert call_kwargs["text"] == "Hello world"
        assert call_kwargs["voice_id"] == "test-voice-id"
        assert call_kwargs["model_id"] == "eleven_flash_v2_5"

    @patch("services.tts.ElevenLabs")
    def test_truncates_long_text(self, mock_elevenlabs_class):
        """Should truncate text longer than model limit (40,000 for flash v2.5)."""
        # Setup mock
        mock_client = Mock()
        mock_tts = Mock()
        mock_tts.convert.return_value = [b"audio"]
        mock_client.text_to_speech = mock_tts
        mock_elevenlabs_class.return_value = mock_client

        # Generate long text (longer than 40,000 chars for eleven_flash_v2_5)
        long_text = "x" * 45000

        # Call function with default model (eleven_flash_v2_5)
        generate_audio(
            text=long_text,
            voice_id="test-voice-id",
            api_key="test-api-key",
        )

        # Check that text was truncated to 40,000 chars
        call_kwargs = mock_tts.convert.call_args.kwargs
        posted_text = call_kwargs["text"]
        assert len(posted_text) == 40000
        assert posted_text.endswith("...")

    @patch("services.tts.ElevenLabs")
    def test_raises_on_auth_error(self, mock_elevenlabs_class):
        """Should raise TTSAPIError on authentication error."""
        # Setup mock to raise auth error
        mock_client = Mock()
        mock_tts = Mock()
        mock_tts.convert.side_effect = Exception("401 Unauthorized")
        mock_client.text_to_speech = mock_tts
        mock_elevenlabs_class.return_value = mock_client

        # Call function and expect error
        with pytest.raises(TTSAPIError, match="Invalid API key"):
            generate_audio(
                text="Test",
                voice_id="voice-id",
                api_key="bad-key",
            )

    @patch("services.tts.ElevenLabs")
    def test_raises_on_payment_required(self, mock_elevenlabs_class):
        """Should raise TTSAPIError on payment required error."""
        # Setup mock to raise payment error
        mock_client = Mock()
        mock_tts = Mock()
        mock_tts.convert.side_effect = Exception("402 payment_required")
        mock_client.text_to_speech = mock_tts
        mock_elevenlabs_class.return_value = mock_client

        # Call function and expect error
        with pytest.raises(TTSAPIError, match="Payment required"):
            generate_audio(
                text="Test",
                voice_id="voice-id",
                api_key="api-key",
            )

    @patch("services.tts.ElevenLabs")
    def test_raises_on_rate_limit(self, mock_elevenlabs_class):
        """Should raise TTSAPIError on rate limit."""
        # Setup mock to raise rate limit error
        mock_client = Mock()
        mock_tts = Mock()
        mock_tts.convert.side_effect = Exception("429 Rate limited")
        mock_client.text_to_speech = mock_tts
        mock_elevenlabs_class.return_value = mock_client

        # Call function and expect error
        with pytest.raises(TTSAPIError, match="Rate limited"):
            generate_audio(
                text="Test",
                voice_id="voice-id",
                api_key="api-key",
            )

    @patch("services.tts.ElevenLabs")
    def test_model_specific_limits(self, mock_elevenlabs_class):
        """Should apply correct character limits for different models."""
        # Setup mock
        mock_client = Mock()
        mock_tts = Mock()
        mock_tts.convert.return_value = [b"audio"]
        mock_client.text_to_speech = mock_tts
        mock_elevenlabs_class.return_value = mock_client

        # Test Flash v2.5 (40,000 char limit)
        long_text = "x" * 45000
        generate_audio(
            text=long_text,
            voice_id="test-voice",
            api_key="test-key",
            model_id="eleven_flash_v2_5",
        )
        posted_text = mock_tts.convert.call_args.kwargs["text"]
        assert len(posted_text) == 40000
        assert posted_text.endswith("...")

        # Test Multilingual v2 (10,000 char limit)
        long_text = "x" * 12000
        generate_audio(
            text=long_text,
            voice_id="test-voice",
            api_key="test-key",
            model_id="eleven_multilingual_v2",
        )
        posted_text = mock_tts.convert.call_args.kwargs["text"]
        assert len(posted_text) == 10000
        assert posted_text.endswith("...")


class TestSaveAudioFile:
    """Tests for save_audio_file function."""

    def test_saves_file_successfully(self, tmp_path):
        """Should save audio file and return duration."""
        # Setup
        audio_data = b"x" * 16000 * 60  # 60 seconds worth of data at 16KB/s
        file_path = tmp_path / "test.mp3"

        # Call function
        duration = save_audio_file(audio_data, str(file_path))

        # Assertions
        assert file_path.exists()
        assert file_path.read_bytes() == audio_data
        assert duration == 60

    def test_creates_parent_directory(self, tmp_path):
        """Should create parent directory if it doesn't exist."""
        # Setup
        audio_data = b"test data"
        nested_path = tmp_path / "nested" / "dir" / "audio.mp3"

        # Call function
        save_audio_file(audio_data, str(nested_path))

        # Assertions
        assert nested_path.exists()
        assert nested_path.parent.exists()

    def test_duration_estimation(self, tmp_path):
        """Should estimate duration from file size."""
        # Setup - 5 minutes at 16KB/s = 4.8 MB
        audio_data = b"x" * (16000 * 60 * 5)
        file_path = tmp_path / "test.mp3"

        # Call function
        duration = save_audio_file(audio_data, str(file_path))

        # Should be approximately 5 minutes (300 seconds)
        assert duration == 300


class TestGetAudioDuration:
    """Tests for get_audio_duration function."""

    def test_returns_duration_for_existing_file(self, tmp_path):
        """Should return duration for existing file."""
        # Create test file (60 seconds worth of data)
        file_path = tmp_path / "test.mp3"
        file_path.write_bytes(b"x" * 16000 * 60)

        # Call function
        duration = get_audio_duration(str(file_path))

        # Should estimate 60 seconds
        assert duration == 60

    def test_returns_none_for_nonexistent_file(self, tmp_path):
        """Should return None for files that don't exist."""
        # Call function with nonexistent path
        duration = get_audio_duration(str(tmp_path / "nonexistent.mp3"))

        # Should return None
        assert duration is None

    def test_empty_file_returns_zero(self, tmp_path):
        """Should return 0 for empty files."""
        # Create empty file
        file_path = tmp_path / "empty.mp3"
        file_path.write_bytes(b"")

        # Call function
        duration = get_audio_duration(str(file_path))

        # Should be 0
        assert duration == 0
