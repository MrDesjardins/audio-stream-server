"""Tests for transcription service."""
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock, mock_open
import pytest
from services.transcription import compress_audio_for_whisper, transcribe_audio, WHISPER_MAX_FILE_SIZE


class TestCompressAudioForWhisper:
    """Tests for compress_audio_for_whisper function."""

    @patch('services.transcription.subprocess.run')
    @patch('services.transcription.os.path.getsize')
    @patch('services.transcription.os.close')
    @patch('services.transcription.tempfile.mkstemp')
    def test_compress_audio_success(self, mock_mkstemp, mock_close, mock_getsize, mock_run):
        """Test successful audio compression."""
        # Mock temp file creation
        mock_mkstemp.return_value = (123, '/tmp/whisper_compressed_test.mp3')

        # Mock file sizes
        mock_getsize.side_effect = [10 * 1024 * 1024, 3 * 1024 * 1024]  # 10MB -> 3MB

        # Mock successful ffmpeg run
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = compress_audio_for_whisper('/path/to/audio.mp3')

        assert result == '/tmp/whisper_compressed_test.mp3'

        # Verify ffmpeg command
        ffmpeg_cmd = mock_run.call_args[0][0]
        assert 'ffmpeg' in ffmpeg_cmd
        assert 'atempo=1.5' in ffmpeg_cmd  # Speed up
        assert '-ac' in ffmpeg_cmd and '1' in ffmpeg_cmd  # Mono
        assert '-b:a' in ffmpeg_cmd and '32k' in ffmpeg_cmd  # Bitrate

    @patch('services.transcription.subprocess.run')
    @patch('services.transcription.os.path.getsize')
    @patch('services.transcription.os.close')
    @patch('services.transcription.tempfile.mkstemp')
    def test_compress_audio_ffmpeg_fails(self, mock_mkstemp, mock_close, mock_getsize, mock_run):
        """Test compression when ffmpeg fails."""
        mock_mkstemp.return_value = (123, '/tmp/test.mp3')
        mock_getsize.return_value = 10 * 1024 * 1024

        # Mock failed ffmpeg run
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "ffmpeg error message"
        mock_run.return_value = mock_result

        with pytest.raises(Exception, match="ffmpeg compression failed"):
            compress_audio_for_whisper('/path/to/audio.mp3')

    @patch('services.transcription.subprocess.run')
    @patch('services.transcription.os.path.getsize')
    @patch('services.transcription.os.path.exists')
    @patch('services.transcription.os.unlink')
    @patch('services.transcription.os.close')
    @patch('services.transcription.tempfile.mkstemp')
    def test_compress_audio_still_too_large(self, mock_mkstemp, mock_close, mock_unlink, mock_exists, mock_getsize, mock_run):
        """Test compression when result is still too large."""
        mock_mkstemp.return_value = (123, '/tmp/test.mp3')
        mock_exists.return_value = True

        # Mock file sizes - compressed is still over limit
        mock_getsize.side_effect = [
            30 * 1024 * 1024,  # Original: 30MB
            26 * 1024 * 1024   # Compressed: 26MB (still > 25MB limit)
        ]

        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        with pytest.raises(Exception, match="still exceeds Whisper limit"):
            compress_audio_for_whisper('/path/to/audio.mp3')

        # Should clean up temp file (may be called more than once due to finally block)
        assert mock_unlink.called

    @patch('services.transcription.subprocess.run')
    @patch('services.transcription.os.path.exists')
    @patch('services.transcription.os.unlink')
    @patch('services.transcription.os.close')
    @patch('services.transcription.tempfile.mkstemp')
    def test_compress_audio_cleans_up_on_error(self, mock_mkstemp, mock_close, mock_unlink, mock_exists, mock_run):
        """Test that temp file is cleaned up on error."""
        mock_mkstemp.return_value = (123, '/tmp/test.mp3')
        mock_exists.return_value = True
        mock_run.side_effect = Exception("Test error")

        with pytest.raises(Exception, match="Test error"):
            compress_audio_for_whisper('/path/to/audio.mp3')

        # Should clean up temp file
        mock_unlink.assert_called_with('/tmp/test.mp3')


class TestTranscribeAudio:
    """Tests for transcribe_audio function."""

    @patch('services.transcription.compress_audio_for_whisper')
    @patch('services.transcription.os.path.getsize')
    @patch('services.transcription.os.path.exists')
    @patch('services.transcription.os.unlink')
    @patch('services.transcription.get_config')
    def test_transcribe_audio_success(self, mock_config, mock_unlink, mock_exists, mock_getsize, mock_compress):
        """Test successful transcription."""
        # Mock config
        config = Mock()
        config.openai_api_key = 'test-key'
        mock_config.return_value = config

        # Mock file operations
        mock_getsize.return_value = 5 * 1024 * 1024  # 5MB file
        mock_compress.return_value = '/tmp/compressed.mp3'
        mock_exists.return_value = True

        # Mock OpenAI client
        with patch('services.transcription.OpenAI') as mock_openai:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.text = "This is the transcribed text"
            mock_client.audio.transcriptions.create.return_value = mock_response
            mock_openai.return_value = mock_client

            with patch('builtins.open', mock_open(read_data=b'audio data')):
                result = transcribe_audio('/path/to/audio.mp3')

            assert result == "This is the transcribed text"

            # Should have compressed the audio
            mock_compress.assert_called_once_with('/path/to/audio.mp3')

            # Should clean up compressed file
            mock_unlink.assert_called_once()

    @patch('services.transcription.get_config')
    def test_transcribe_audio_no_api_key(self, mock_config):
        """Test transcription fails without API key."""
        config = Mock()
        config.openai_api_key = None
        mock_config.return_value = config

        with pytest.raises(ValueError, match="OpenAI API key not configured"):
            transcribe_audio('/path/to/audio.mp3')

    @patch('services.transcription.compress_audio_for_whisper')
    @patch('services.transcription.os.path.getsize')
    @patch('services.transcription.get_config')
    def test_transcribe_audio_compression_fails(self, mock_config, mock_getsize, mock_compress):
        """Test transcription when compression fails."""
        config = Mock()
        config.openai_api_key = 'test-key'
        mock_config.return_value = config

        mock_getsize.return_value = 5 * 1024 * 1024
        mock_compress.side_effect = Exception("Compression failed")

        with pytest.raises(Exception, match="Audio compression failed"):
            transcribe_audio('/path/to/audio.mp3')

    @patch('services.transcription.compress_audio_for_whisper')
    @patch('services.transcription.os.path.getsize')
    @patch('services.transcription.os.path.exists')
    @patch('services.transcription.os.unlink')
    @patch('services.transcription.get_config')
    @patch('services.transcription.time.sleep')
    def test_transcribe_audio_retries_on_failure(self, mock_sleep, mock_config, mock_unlink, mock_exists, mock_getsize, mock_compress):
        """Test transcription retries on failure."""
        config = Mock()
        config.openai_api_key = 'test-key'
        mock_config.return_value = config

        mock_getsize.return_value = 5 * 1024 * 1024
        mock_compress.return_value = '/tmp/compressed.mp3'
        mock_exists.return_value = True

        with patch('services.transcription.OpenAI') as mock_openai:
            mock_client = Mock()
            mock_client.audio.transcriptions.create.side_effect = [
                Exception("API error"),
                Exception("API error"),
                "Success on third try"
            ]
            mock_openai.return_value = mock_client

            with patch('builtins.open', mock_open(read_data=b'audio data')):
                result = transcribe_audio('/path/to/audio.mp3', retries=3)

            assert result == "Success on third try"

            # Should have slept between retries
            assert mock_sleep.call_count == 2

    @patch('services.transcription.compress_audio_for_whisper')
    @patch('services.transcription.os.path.getsize')
    @patch('services.transcription.os.path.exists')
    @patch('services.transcription.os.unlink')
    @patch('services.transcription.get_config')
    @patch('services.transcription.time.sleep')
    def test_transcribe_audio_fails_after_retries(self, mock_sleep, mock_config, mock_unlink, mock_exists, mock_getsize, mock_compress):
        """Test transcription fails after all retries."""
        config = Mock()
        config.openai_api_key = 'test-key'
        mock_config.return_value = config

        mock_getsize.return_value = 5 * 1024 * 1024
        mock_compress.return_value = '/tmp/compressed.mp3'
        mock_exists.return_value = True

        with patch('services.transcription.OpenAI') as mock_openai:
            mock_client = Mock()
            mock_client.audio.transcriptions.create.side_effect = Exception("API error")
            mock_openai.return_value = mock_client

            with patch('builtins.open', mock_open(read_data=b'audio data')):
                with pytest.raises(Exception, match="Transcription failed after 3 attempts"):
                    transcribe_audio('/path/to/audio.mp3', retries=3)

    @patch('services.transcription.compress_audio_for_whisper')
    @patch('services.transcription.os.path.getsize')
    @patch('services.transcription.os.path.exists')
    @patch('services.transcription.os.unlink')
    @patch('services.transcription.get_config')
    def test_transcribe_audio_handles_string_response(self, mock_config, mock_unlink, mock_exists, mock_getsize, mock_compress):
        """Test transcription handles string response from API."""
        config = Mock()
        config.openai_api_key = 'test-key'
        mock_config.return_value = config

        mock_getsize.return_value = 5 * 1024 * 1024
        mock_compress.return_value = '/tmp/compressed.mp3'
        mock_exists.return_value = True

        with patch('services.transcription.OpenAI') as mock_openai:
            mock_client = Mock()
            # API returns string directly
            mock_client.audio.transcriptions.create.return_value = "Direct string response"
            mock_openai.return_value = mock_client

            with patch('builtins.open', mock_open(read_data=b'audio data')):
                result = transcribe_audio('/path/to/audio.mp3')

            assert result == "Direct string response"

    @patch('services.transcription.compress_audio_for_whisper')
    @patch('services.transcription.os.path.getsize')
    @patch('services.transcription.os.path.exists')
    @patch('services.transcription.os.unlink')
    @patch('services.transcription.get_config')
    def test_transcribe_audio_cleans_up_compressed_file(self, mock_config, mock_unlink, mock_exists, mock_getsize, mock_compress):
        """Test that compressed file is always cleaned up."""
        config = Mock()
        config.openai_api_key = 'test-key'
        mock_config.return_value = config

        mock_getsize.return_value = 5 * 1024 * 1024
        mock_compress.return_value = '/tmp/compressed.mp3'
        mock_exists.return_value = True

        with patch('services.transcription.OpenAI') as mock_openai:
            mock_client = Mock()
            mock_client.audio.transcriptions.create.side_effect = Exception("API error")
            mock_openai.return_value = mock_client

            with patch('builtins.open', mock_open(read_data=b'audio data')):
                try:
                    transcribe_audio('/path/to/audio.mp3', retries=1)
                except:
                    pass

            # Should still clean up compressed file even on error
            mock_unlink.assert_called()
