"""Tests for transcription service."""

from unittest.mock import Mock, patch, mock_open
import pytest
from services.transcription import (
    compress_audio_for_whisper,
    transcribe_audio,
)


class TestCompressAudioForWhisper:
    """Tests for compress_audio_for_whisper function."""

    @patch("services.transcription.subprocess.run")
    @patch("services.transcription.Path")
    @patch("services.transcription.os.path.getsize")
    @patch("services.transcription.os.close")
    @patch("services.transcription.tempfile.mkstemp")
    def test_compress_audio_success(
        self, mock_mkstemp, mock_close, mock_getsize, mock_path, mock_run
    ):
        """Test successful audio compression."""
        # Mock temp file creation
        mock_mkstemp.return_value = (123, "/tmp/whisper_compressed_test.mp3")

        # Mock Path with .expanduser().resolve() chain
        # First call: Path(temp_path) - no expanduser/resolve
        mock_temp_path_instance = Mock()
        compressed_stat = Mock()
        compressed_stat.st_size = 3 * 1024 * 1024
        mock_temp_path_instance.stat.return_value = compressed_stat

        # Second call: Path(audio_path).expanduser().resolve() - for path expansion
        mock_expanded_instance = Mock()
        mock_expanded_instance.resolve.return_value = Mock(
            __str__=lambda x: "/expanded/path/audio.mp3"
        )

        mock_audio_path_instance = Mock()
        mock_audio_path_instance.expanduser.return_value = mock_expanded_instance

        # Third call: Path(expanded_audio_path).stat() - for original file size
        original_stat = Mock()
        original_stat.st_size = 10 * 1024 * 1024

        mock_original_path_instance = Mock()
        mock_original_path_instance.stat.return_value = original_stat

        mock_path.side_effect = [
            mock_audio_path_instance,
            mock_temp_path_instance,
            mock_original_path_instance,
        ]

        # Mock file sizes
        mock_getsize.side_effect = [10 * 1024 * 1024, 3 * 1024 * 1024]  # 10MB -> 3MB

        # Mock successful ffmpeg run
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = compress_audio_for_whisper("/path/to/audio.mp3")

        assert result == "/tmp/whisper_compressed_test.mp3"

        # Verify ffmpeg command
        ffmpeg_cmd = mock_run.call_args[0][0]
        assert "ffmpeg" in ffmpeg_cmd
        assert "atempo=1.5" in ffmpeg_cmd  # Speed up
        assert "-ac" in ffmpeg_cmd and "1" in ffmpeg_cmd  # Mono
        assert "-b:a" in ffmpeg_cmd and "32k" in ffmpeg_cmd  # Bitrate

    @patch("services.transcription.subprocess.run")
    @patch("services.transcription.Path")
    @patch("services.transcription.os.path.getsize")
    @patch("services.transcription.os.close")
    @patch("services.transcription.tempfile.mkstemp")
    def test_compress_audio_ffmpeg_fails(
        self, mock_mkstemp, mock_close, mock_getsize, mock_path, mock_run
    ):
        """Test compression when ffmpeg fails."""
        mock_mkstemp.return_value = (123, "/tmp/test.mp3")
        mock_getsize.return_value = 10 * 1024 * 1024

        # Mock Path.stat() (not actually called since ffmpeg fails)
        mock_path_instance = Mock()
        mock_path.return_value = mock_path_instance

        # Mock failed ffmpeg run
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "ffmpeg error message"
        mock_run.return_value = mock_result

        with pytest.raises(Exception, match="ffmpeg compression failed"):
            compress_audio_for_whisper("/path/to/audio.mp3")

    @patch("services.transcription.subprocess.run")
    @patch("services.transcription.Path")
    @patch("services.transcription.os.path.getsize")
    @patch("services.transcription.os.path.exists")
    @patch("services.transcription.os.unlink")
    @patch("services.transcription.os.close")
    @patch("services.transcription.tempfile.mkstemp")
    def test_compress_audio_still_too_large(
        self,
        mock_mkstemp,
        mock_close,
        mock_unlink,
        mock_exists,
        mock_getsize,
        mock_path,
        mock_run,
    ):
        """Test compression when result is still too large."""
        mock_mkstemp.return_value = (123, "/tmp/test.mp3")

        # Mock Path calls in order:
        # 1. Path(audio_path).expanduser().resolve() - for path expansion
        mock_expanded_instance = Mock()
        mock_expanded_instance.resolve.return_value = Mock(
            __str__=lambda x: "/expanded/path/audio.mp3"
        )

        mock_audio_path_instance = Mock()
        mock_audio_path_instance.expanduser.return_value = mock_expanded_instance

        # 2. Path(temp_path).stat() - for compressed file size
        mock_temp_path_instance = Mock()
        compressed_stat = Mock()
        compressed_stat.st_size = 30 * 1024 * 1024  # 30MB (over 25MB limit)
        mock_temp_path_instance.stat.return_value = compressed_stat

        # 3. Path(expanded_audio_path).stat() - for original file size
        original_stat = Mock()
        original_stat.st_size = 50 * 1024 * 1024  # 50MB original

        mock_original_path_instance = Mock()
        mock_original_path_instance.stat.return_value = original_stat

        # 4. Path(temp_path) - for cleanup in except block
        mock_cleanup_path_instance = Mock()
        mock_cleanup_path_instance.exists.return_value = True

        mock_path.side_effect = [
            mock_audio_path_instance,
            mock_temp_path_instance,
            mock_original_path_instance,
            mock_cleanup_path_instance,
        ]
        mock_exists.return_value = True

        # Mock file sizes - compressed is still over limit
        mock_getsize.side_effect = [
            30 * 1024 * 1024,  # Original: 30MB
            26 * 1024 * 1024,  # Compressed: 26MB (still > 25MB limit)
        ]

        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        with pytest.raises(Exception, match="still exceeds Whisper limit"):
            compress_audio_for_whisper("/path/to/audio.mp3")

        # Should clean up temp file (may be called more than once due to finally block)
        assert mock_unlink.called

    @patch("services.transcription.subprocess.run")
    @patch("services.transcription.Path")
    @patch("services.transcription.os.path.exists")
    @patch("services.transcription.os.unlink")
    @patch("services.transcription.os.close")
    @patch("services.transcription.tempfile.mkstemp")
    def test_compress_audio_cleans_up_on_error(
        self, mock_mkstemp, mock_close, mock_unlink, mock_exists, mock_path, mock_run
    ):
        """Test that temp file is cleaned up on error."""
        mock_mkstemp.return_value = (123, "/tmp/test.mp3")

        # Mock Path - the cleanup code creates Path(temp_path) and calls .exists() and .unlink()
        mock_path_instance = Mock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance

        mock_run.side_effect = Exception("Test error")

        with pytest.raises(Exception, match="Test error"):
            compress_audio_for_whisper("/path/to/audio.mp3")

        # Should clean up temp file using Path.unlink()
        mock_path_instance.unlink.assert_called_once()


class TestTranscribeAudio:
    """Tests for transcribe_audio function."""

    @patch("services.transcription.compress_audio_for_whisper")
    @patch("services.transcription.Path")
    @patch("services.transcription.os.path.getsize")
    @patch("services.transcription.os.path.exists")
    @patch("services.transcription.os.unlink")
    @patch("services.transcription.get_config")
    def test_transcribe_audio_success(
        self,
        mock_config,
        mock_unlink,
        mock_exists,
        mock_getsize,
        mock_path,
        mock_compress,
    ):
        """Test successful transcription."""
        # Mock config
        config = Mock()
        config.transcription_provider = "openai"
        config.openai_api_key = "test-key"
        mock_config.return_value = config

        # Mock Path - needs to handle two calls:
        # 1. Path(audio_path).expanduser().resolve().stat() for file size check
        # 2. Path(compressed_path) for cleanup (no expanduser/resolve)
        mock_stat_instance = Mock()
        mock_stat_instance.st_size = 5 * 1024 * 1024  # 5MB file

        # Create the chain: instance.expanduser().resolve().stat() returns mock_stat_instance
        mock_resolved_instance = Mock()
        mock_resolved_instance.stat.return_value = mock_stat_instance

        mock_expanded_instance = Mock()
        mock_expanded_instance.resolve.return_value = mock_resolved_instance

        mock_audio_path_instance = Mock()
        mock_audio_path_instance.expanduser.return_value = mock_expanded_instance

        mock_compressed_path_instance = Mock()
        mock_compressed_path_instance.exists.return_value = True

        mock_path.side_effect = [
            mock_audio_path_instance,
            mock_compressed_path_instance,
        ]

        # Mock file operations
        mock_getsize.return_value = 5 * 1024 * 1024  # 5MB file
        mock_compress.return_value = "/tmp/compressed.mp3"
        mock_exists.return_value = True

        # Mock OpenAI client
        with patch("services.transcription.get_openai_client") as mock_get_client:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.text = "This is the transcribed text"
            mock_client.audio.transcriptions.create.return_value = mock_response
            mock_get_client.return_value = mock_client

            with patch("builtins.open", mock_open(read_data=b"audio data")):
                result = transcribe_audio("/path/to/audio.mp3")

            assert result == "This is the transcribed text"

            # Should have compressed the audio
            mock_compress.assert_called_once_with("/path/to/audio.mp3")

            # Should clean up compressed file using Path.unlink()
            mock_compressed_path_instance.unlink.assert_called_once()

    @patch("services.transcription.get_config")
    def test_transcribe_audio_no_api_key(self, mock_config):
        """Test transcription fails without API key."""
        config = Mock()
        config.transcription_provider = "openai"
        config.openai_api_key = None
        mock_config.return_value = config

        with pytest.raises(ValueError, match="OpenAI API key not configured"):
            transcribe_audio("/path/to/audio.mp3")

    @patch("services.transcription.get_openai_client")
    @patch("services.transcription.compress_audio_for_whisper")
    @patch("services.transcription.Path")
    @patch("services.transcription.os.path.getsize")
    @patch("services.transcription.get_config")
    def test_transcribe_audio_compression_fails(
        self, mock_config, mock_getsize, mock_path, mock_compress, mock_get_client
    ):
        """Test transcription when compression fails."""
        config = Mock()
        config.transcription_provider = "openai"
        config.openai_api_key = "test-key"
        mock_config.return_value = config

        # Mock Path.expanduser().resolve().stat()
        mock_stat = Mock()
        mock_stat.st_size = 5 * 1024 * 1024

        # Create the chain: instance.expanduser().resolve().stat() returns mock_stat
        mock_resolved_instance = Mock()
        mock_resolved_instance.stat.return_value = mock_stat

        mock_expanded_instance = Mock()
        mock_expanded_instance.resolve.return_value = mock_resolved_instance

        mock_audio_path_instance = Mock()
        mock_audio_path_instance.expanduser.return_value = mock_expanded_instance
        mock_path.return_value = mock_audio_path_instance

        # Mock OpenAI client (created before compression)
        mock_client = Mock()
        mock_get_client.return_value = mock_client

        mock_getsize.return_value = 5 * 1024 * 1024
        mock_compress.side_effect = Exception("Compression failed")

        with pytest.raises(Exception, match="Audio compression failed"):
            transcribe_audio("/path/to/audio.mp3")

    @patch("services.transcription.compress_audio_for_whisper")
    @patch("services.transcription.Path")
    @patch("services.transcription.os.path.getsize")
    @patch("services.transcription.os.path.exists")
    @patch("services.transcription.os.unlink")
    @patch("services.transcription.get_config")
    @patch("services.transcription.time.sleep")
    def test_transcribe_audio_retries_on_failure(
        self,
        mock_sleep,
        mock_config,
        mock_unlink,
        mock_exists,
        mock_getsize,
        mock_path,
        mock_compress,
    ):
        """Test transcription retries on failure."""
        config = Mock()
        config.transcription_provider = "openai"
        config.openai_api_key = "test-key"

        # Mock Path - needs to handle two calls:
        # 1. Path(audio_path).expanduser().resolve().stat() for file size check
        # 2. Path(compressed_path) for cleanup
        mock_stat = Mock()
        mock_stat.st_size = 5 * 1024 * 1024

        # Create the chain: instance.expanduser().resolve().stat() returns mock_stat
        mock_resolved_instance = Mock()
        mock_resolved_instance.stat.return_value = mock_stat

        mock_expanded_instance = Mock()
        mock_expanded_instance.resolve.return_value = mock_resolved_instance

        mock_audio_path_instance = Mock()
        mock_audio_path_instance.expanduser.return_value = mock_expanded_instance

        mock_compressed_path_instance = Mock()
        mock_compressed_path_instance.exists.return_value = True

        mock_path.side_effect = [
            mock_audio_path_instance,
            mock_compressed_path_instance,
        ]
        mock_config.return_value = config

        mock_getsize.return_value = 5 * 1024 * 1024
        mock_compress.return_value = "/tmp/compressed.mp3"
        mock_exists.return_value = True

        with patch("services.transcription.get_openai_client") as mock_get_client:
            mock_client = Mock()
            mock_client.audio.transcriptions.create.side_effect = [
                Exception("API error"),
                Exception("API error"),
                "Success on third try",
            ]
            mock_get_client.return_value = mock_client

            with patch("builtins.open", mock_open(read_data=b"audio data")):
                result = transcribe_audio("/path/to/audio.mp3", retries=3)

            assert result == "Success on third try"

            # Should have slept between retries
            assert mock_sleep.call_count == 2

    @patch("services.transcription.compress_audio_for_whisper")
    @patch("services.transcription.Path")
    @patch("services.transcription.os.path.getsize")
    @patch("services.transcription.os.path.exists")
    @patch("services.transcription.os.unlink")
    @patch("services.transcription.get_config")
    @patch("services.transcription.time.sleep")
    def test_transcribe_audio_fails_after_retries(
        self,
        mock_sleep,
        mock_config,
        mock_unlink,
        mock_exists,
        mock_getsize,
        mock_path,
        mock_compress,
    ):
        """Test transcription fails after all retries."""
        config = Mock()
        config.transcription_provider = "openai"
        config.openai_api_key = "test-key"
        mock_config.return_value = config

        # Mock Path - needs to handle two calls:
        # 1. Path(audio_path).expanduser().resolve().stat() for file size check
        # 2. Path(compressed_path) for cleanup

        # Create proper chain: Path(x).expanduser().resolve().stat()
        mock_stat = Mock()
        mock_stat.st_size = 5 * 1024 * 1024

        mock_resolved_instance = Mock()
        mock_resolved_instance.stat.return_value = mock_stat

        mock_expanded_instance = Mock()
        mock_expanded_instance.resolve.return_value = mock_resolved_instance

        mock_audio_path_instance = Mock()
        mock_audio_path_instance.expanduser.return_value = mock_expanded_instance

        mock_compressed_path_instance = Mock()
        mock_compressed_path_instance.exists.return_value = True

        mock_path.side_effect = [
            mock_audio_path_instance,
            mock_compressed_path_instance,
        ]

        mock_getsize.return_value = 5 * 1024 * 1024
        mock_compress.return_value = "/tmp/compressed.mp3"
        mock_exists.return_value = True

        with patch("services.transcription.get_openai_client") as mock_get_client:
            mock_client = Mock()
            mock_client.audio.transcriptions.create.side_effect = Exception("API error")
            mock_get_client.return_value = mock_client

            with patch("builtins.open", mock_open(read_data=b"audio data")):
                with pytest.raises(
                    Exception, match="Transcription failed after 3 attempts"
                ):
                    transcribe_audio("/path/to/audio.mp3", retries=3)

    @patch("services.transcription.compress_audio_for_whisper")
    @patch("services.transcription.Path")
    @patch("services.transcription.os.path.getsize")
    @patch("services.transcription.os.path.exists")
    @patch("services.transcription.os.unlink")
    @patch("services.transcription.get_config")
    def test_transcribe_audio_handles_string_response(
        self,
        mock_config,
        mock_unlink,
        mock_exists,
        mock_getsize,
        mock_path,
        mock_compress,
    ):
        """Test transcription handles string response from API."""
        # Mock config
        config = Mock()
        config.transcription_provider = "openai"
        config.openai_api_key = "test-key"
        mock_config.return_value = config

        # Mock Path - needs to handle two calls:
        # 1. Path(audio_path).expanduser().resolve().stat() for file size check
        # 2. Path(compressed_path) for cleanup
        mock_audio_path_instance = Mock()
        mock_stat = Mock()
        mock_stat.st_size = 5 * 1024 * 1024
        mock_audio_path_instance.stat.return_value = mock_stat
        # Make expanduser().resolve() return the same instance
        mock_audio_path_instance.expanduser.return_value.resolve.return_value = (
            mock_audio_path_instance
        )

        mock_compressed_path_instance = Mock()
        mock_compressed_path_instance.exists.return_value = True

        mock_path.side_effect = [
            mock_audio_path_instance,
            mock_compressed_path_instance,
        ]

        mock_getsize.return_value = 5 * 1024 * 1024
        mock_compress.return_value = "/tmp/compressed.mp3"
        mock_exists.return_value = True

        with patch("services.transcription.get_openai_client") as mock_get_client:
            mock_client = Mock()
            # API returns string directly
            mock_client.audio.transcriptions.create.return_value = (
                "Direct string response"
            )
            mock_get_client.return_value = mock_client

            with patch("builtins.open", mock_open(read_data=b"audio data")):
                result = transcribe_audio("/path/to/audio.mp3")

            assert result == "Direct string response"

    @patch("services.transcription.compress_audio_for_whisper")
    @patch("services.transcription.Path")
    @patch("services.transcription.os.path.getsize")
    @patch("services.transcription.os.path.exists")
    @patch("services.transcription.os.unlink")
    @patch("services.transcription.get_config")
    def test_transcribe_audio_cleans_up_compressed_file(
        self,
        mock_config,
        mock_unlink,
        mock_exists,
        mock_getsize,
        mock_path,
        mock_compress,
    ):
        """Test that compressed file is always cleaned up."""
        config = Mock()
        config.transcription_provider = "openai"
        config.openai_api_key = "test-key"
        mock_config.return_value = config

        # Mock Path - needs to handle two calls:
        # 1. Path(audio_path).expanduser().resolve().stat() for file size check
        # 2. Path(compressed_path) for cleanup

        # Create proper chain: Path(x).expanduser().resolve().stat()
        mock_stat_instance = Mock()
        mock_stat_instance.st_size = 5 * 1024 * 1024

        mock_resolved_instance = Mock()
        mock_resolved_instance.stat.return_value = mock_stat_instance

        mock_expanded_instance = Mock()
        mock_expanded_instance.resolve.return_value = mock_resolved_instance

        mock_audio_path_instance = Mock()
        mock_audio_path_instance.expanduser.return_value = mock_expanded_instance

        mock_compressed_path_instance = Mock()
        mock_compressed_path_instance.exists.return_value = True

        mock_path.side_effect = [
            mock_audio_path_instance,
            mock_compressed_path_instance,
        ]

        mock_getsize.return_value = 5 * 1024 * 1024
        mock_compress.return_value = "/tmp/compressed.mp3"
        mock_exists.return_value = True

        with patch("services.transcription.get_openai_client") as mock_get_client:
            mock_client = Mock()
            mock_client.audio.transcriptions.create.side_effect = Exception("API error")
            mock_get_client.return_value = mock_client

            with patch("builtins.open", mock_open(read_data=b"audio data")):
                with pytest.raises(Exception, match="API error"):
                    transcribe_audio("/path/to/audio.mp3", retries=1)

            # Should still clean up compressed file even on error using Path.unlink()
            mock_compressed_path_instance.unlink.assert_called_once()
