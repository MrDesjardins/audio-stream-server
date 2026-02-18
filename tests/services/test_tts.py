"""Tests for TTS service."""

import pytest
from unittest.mock import Mock, patch

from services.tts import (
    extract_summary_text_for_tts,
    generate_audio,
    save_audio_file,
    get_audio_duration,
    TTSAPIError,
    _split_text_into_chunks,
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


class TestSplitTextIntoChunks:
    """Tests for _split_text_into_chunks helper."""

    def test_short_text_returned_as_single_chunk(self):
        """Text under the limit should come back as one chunk."""
        text = "Hello world. This is a short sentence."
        chunks = _split_text_into_chunks(text, max_chars=4096)
        assert chunks == [text]

    def test_splits_at_sentence_boundary(self):
        """Long text should be split between sentences, not mid-word."""
        sentence = "This is a sentence."
        # Build text that just exceeds 100 chars when fully joined
        text = (" " + sentence) * 6  # ~120 chars
        chunks = _split_text_into_chunks(text, max_chars=100)

        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 100
        # Rejoin should recover the original content
        assert " ".join(chunks).replace("  ", " ").strip() == text.strip()

    def test_splits_at_paragraph_boundary(self):
        """Should prefer splitting at paragraph breaks."""
        para = "Short paragraph."
        text = (para + "\n\n") * 5 + para
        chunks = _split_text_into_chunks(text, max_chars=50)

        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 50

    def test_hard_splits_oversized_sentence(self):
        """A single sentence longer than max_chars should still be split."""
        # One sentence with no internal punctuation
        long_sentence = "word " * 100  # 500 chars
        chunks = _split_text_into_chunks(long_sentence, max_chars=100)

        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 100

    def test_all_content_preserved(self):
        """No text should be dropped when splitting."""
        sentence = "Another sentence here."
        text = (" " + sentence) * 300  # ~7200 chars
        chunks = _split_text_into_chunks(text, max_chars=4096)

        combined = " ".join(chunks)
        # Every sentence should appear in the output
        assert combined.count(sentence) == 300

    def test_exact_limit_text_is_single_chunk(self):
        """Text exactly at the limit should not be split."""
        text = "x" * 4096
        chunks = _split_text_into_chunks(text, max_chars=4096)
        assert len(chunks) == 1
        assert chunks[0] == text


class TestGenerateAudio:
    """Tests for generate_audio function."""

    @patch("services.tts.get_tracked_openai_client")
    def test_successful_generation_openai(self, mock_get_client):
        """Should generate audio successfully with OpenAI provider."""
        # Setup mock
        mock_client = Mock()
        mock_response = Mock()
        mock_response.read.return_value = b"fake audio data"
        mock_client.text_to_speech.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Call function
        result = generate_audio(
            text="Hello world",
            provider="openai",
            voice="alloy",
            model="tts-1",
        )

        # Assertions
        assert result == b"fake audio data"
        mock_get_client.assert_called_once()
        mock_client.text_to_speech.assert_called_once()

        # Check parameters
        call_kwargs = mock_client.text_to_speech.call_args.kwargs
        assert call_kwargs["text"] == "Hello world"
        assert call_kwargs["voice"] == "alloy"
        assert call_kwargs["model"] == "tts-1"
        assert call_kwargs["feature"] == "tts"

    @patch("services.tts.ElevenLabs")
    def test_successful_generation_elevenlabs(self, mock_elevenlabs_class):
        """Should generate audio successfully with ElevenLabs provider."""
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
            api_key="test-api-key",
            provider="elevenlabs",
            voice="test-voice-id",
            model="eleven_flash_v2_5",
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

    @patch("services.tts.get_tracked_openai_client")
    def test_splits_long_text_openai(self, mock_get_client):
        """Should split text into chunks for OpenAI (not truncate)."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.read.return_value = b"chunk"
        mock_client.text_to_speech.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Build text that spans two chunks: 250 sentences of ~20 chars each = ~5000 chars
        sentence = "This is a sentence."
        long_text = (" " + sentence) * 250  # ~5000 chars, needs 2 chunks

        result = generate_audio(text=long_text, provider="openai")

        # Should have made multiple API calls, each with text under 4096 chars
        assert mock_client.text_to_speech.call_count > 1
        for call in mock_client.text_to_speech.call_args_list:
            assert len(call.kwargs["text"]) <= 4096

        # Result should be concatenated audio from all chunks
        expected = b"chunk" * mock_client.text_to_speech.call_count
        assert result == expected

    @patch("services.tts.ElevenLabs")
    def test_splits_long_text_elevenlabs(self, mock_elevenlabs_class):
        """Should split text into chunks for ElevenLabs (not truncate)."""
        mock_client = Mock()
        mock_tts = Mock()
        mock_tts.convert.return_value = [b"chunk"]
        mock_client.text_to_speech = mock_tts
        mock_elevenlabs_class.return_value = mock_client

        # Build text that spans two chunks for eleven_multilingual_v2 (10K limit)
        sentence = "This is a sentence."
        long_text = (" " + sentence) * 600  # ~12000 chars, needs 2 chunks

        result = generate_audio(
            text=long_text,
            api_key="test-api-key",
            provider="elevenlabs",
            voice="test-voice-id",
            model="eleven_multilingual_v2",
        )

        # Should have made multiple API calls, each with text under 10,000 chars
        assert mock_tts.convert.call_count > 1
        for call in mock_tts.convert.call_args_list:
            assert len(call.kwargs["text"]) <= 10000

        # Result should be concatenated audio from all chunks
        expected = b"chunk" * mock_tts.convert.call_count
        assert result == expected

    @patch("services.tts.get_tracked_openai_client")
    def test_raises_on_auth_error_openai(self, mock_get_client):
        """Should raise TTSAPIError on OpenAI authentication error."""
        # Setup mock to raise auth error
        mock_client = Mock()
        mock_client.text_to_speech.side_effect = Exception("401 Unauthorized")
        mock_get_client.return_value = mock_client

        # Call function and expect error
        with pytest.raises(TTSAPIError, match="Invalid OpenAI API key"):
            generate_audio(
                text="Test",
                provider="openai",
            )

    @patch("services.tts.ElevenLabs")
    def test_raises_on_auth_error_elevenlabs(self, mock_elevenlabs_class):
        """Should raise TTSAPIError on ElevenLabs authentication error."""
        # Setup mock to raise auth error
        mock_client = Mock()
        mock_tts = Mock()
        mock_tts.convert.side_effect = Exception("401 Unauthorized")
        mock_client.text_to_speech = mock_tts
        mock_elevenlabs_class.return_value = mock_client

        # Call function and expect error
        with pytest.raises(TTSAPIError, match="Invalid ElevenLabs API key"):
            generate_audio(
                text="Test",
                api_key="bad-key",
                provider="elevenlabs",
                voice="voice-id",
            )

    @patch("services.tts.ElevenLabs")
    def test_raises_on_quota_exceeded(self, mock_elevenlabs_class):
        """Should raise TTSAPIError on quota exceeded error."""
        # Setup mock to raise quota error
        mock_client = Mock()
        mock_tts = Mock()
        mock_tts.convert.side_effect = Exception("quota_exceeded: insufficient credits")
        mock_client.text_to_speech = mock_tts
        mock_elevenlabs_class.return_value = mock_client

        # Call function and expect error
        with pytest.raises(TTSAPIError, match="Quota exceeded"):
            generate_audio(
                text="Test",
                api_key="api-key",
                provider="elevenlabs",
                voice="voice-id",
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
                api_key="api-key",
                provider="elevenlabs",
                voice="voice-id",
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
                api_key="api-key",
                provider="elevenlabs",
                voice="voice-id",
            )

    @patch("services.tts.ElevenLabs")
    def test_model_specific_chunk_limits(self, mock_elevenlabs_class):
        """Should respect per-model character limits when splitting chunks."""
        mock_client = Mock()
        mock_tts = Mock()
        mock_tts.convert.return_value = [b"audio"]
        mock_client.text_to_speech = mock_tts
        mock_elevenlabs_class.return_value = mock_client

        sentence = "This is a sentence."

        # Flash v2.5: 40,000 char limit — short text fits in one call
        short_text = sentence * 10  # ~200 chars
        mock_tts.reset_mock()
        generate_audio(
            text=short_text,
            api_key="test-key",
            provider="elevenlabs",
            voice="test-voice",
            model="eleven_flash_v2_5",
        )
        assert mock_tts.convert.call_count == 1
        assert len(mock_tts.convert.call_args.kwargs["text"]) <= 40000

        # Multilingual v2: 10,000 char limit — longer text splits into chunks
        long_text = (" " + sentence) * 600  # ~12000 chars
        mock_tts.reset_mock()
        generate_audio(
            text=long_text,
            api_key="test-key",
            provider="elevenlabs",
            voice="test-voice",
            model="eleven_multilingual_v2",
        )
        assert mock_tts.convert.call_count > 1
        for call in mock_tts.convert.call_args_list:
            assert len(call.kwargs["text"]) <= 10000

    def test_raises_on_invalid_provider(self):
        """Should raise ValueError on invalid provider."""
        with pytest.raises(ValueError, match="Unsupported TTS provider"):
            generate_audio(
                text="Test",
                api_key="test-key",
                provider="invalid",
            )

    def test_raises_on_elevenlabs_without_voice(self):
        """Should raise ValueError when using ElevenLabs without voice_id."""
        with pytest.raises(ValueError, match="ElevenLabs requires a voice_id"):
            generate_audio(
                text="Test",
                api_key="test-key",
                provider="elevenlabs",
            )


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
