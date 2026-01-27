"""Tests for streaming service."""

import os
from unittest.mock import Mock, patch, MagicMock
import pytest
from services.streaming import start_youtube_stream


@pytest.fixture
def mock_broadcaster():
    """Mock StreamBroadcaster."""
    broadcaster = Mock()
    broadcaster.start_broadcasting = Mock()
    return broadcaster


@pytest.fixture
def mock_config():
    """Mock configuration."""
    config = Mock()
    config.transcription_enabled = False
    config.get_audio_path = lambda vid: f"/tmp/audio-test/{vid}.mp3"
    return config


@pytest.fixture
def mock_audio_cache():
    """Mock audio cache."""
    cache = Mock()
    cache.check_file_exists = Mock(return_value=False)
    return cache


class TestStartYoutubeStream:
    """Tests for start_youtube_stream function."""

    @patch("services.streaming.subprocess.Popen")
    @patch("services.streaming.get_audio_cache")
    @patch("services.streaming.config")
    def test_stream_without_cache_no_transcription(
        self,
        mock_config_module,
        mock_get_cache,
        mock_popen,
        mock_broadcaster,
        mock_config,
        mock_audio_cache,
    ):
        """Test streaming from YouTube without cache and transcription disabled."""
        # Setup mocks
        mock_config_module.transcription_enabled = False
        mock_config_module.get_audio_path = mock_config.get_audio_path
        mock_get_cache.return_value = mock_audio_cache

        # Mock subprocess processes
        mock_yt_proc = Mock()
        mock_yt_proc.stdout = Mock()
        mock_ffmpeg_proc = Mock()

        mock_popen.side_effect = [mock_yt_proc, mock_ffmpeg_proc]

        # Call function
        result = start_youtube_stream(
            "test123", skip_transcription=False, broadcaster=mock_broadcaster
        )

        # Verify yt-dlp command
        assert mock_popen.call_count == 2
        yt_cmd_call = mock_popen.call_args_list[0]
        yt_cmd = yt_cmd_call[0][0]
        assert "/usr/local/bin/yt-dlp" in yt_cmd
        assert "bestaudio" in yt_cmd[2]
        assert "--no-playlist" in yt_cmd
        assert "https://www.youtube.com/watch?v=test123" in yt_cmd

        # Verify ffmpeg command
        ffmpeg_cmd_call = mock_popen.call_args_list[1]
        ffmpeg_cmd = ffmpeg_cmd_call[0][0]
        assert "ffmpeg" in ffmpeg_cmd
        assert "-err_detect" in ffmpeg_cmd
        assert "ignore_err" in ffmpeg_cmd
        assert "-bufsize" in ffmpeg_cmd
        assert "2048k" in ffmpeg_cmd
        assert "-b:a" in ffmpeg_cmd
        assert "192k" in ffmpeg_cmd

        # Verify broadcaster was started
        mock_broadcaster.start_broadcasting.assert_called_once_with(mock_ffmpeg_proc)

        # Verify return value
        assert result == mock_ffmpeg_proc

    @patch("services.streaming.subprocess.Popen")
    @patch("services.streaming.get_audio_cache")
    @patch("services.streaming.config")
    @patch("services.streaming.logger")
    def test_stream_without_cache_with_transcription(
        self,
        mock_logger,
        mock_config_module,
        mock_get_cache,
        mock_popen,
        mock_broadcaster,
        mock_config,
        mock_audio_cache,
    ):
        """Test streaming from YouTube with transcription enabled."""
        # Setup mocks
        mock_config_module.transcription_enabled = True
        mock_config_module.get_audio_path = mock_config.get_audio_path
        mock_get_cache.return_value = mock_audio_cache

        # Mock subprocess processes
        mock_yt_proc = Mock()
        mock_yt_proc.stdout = Mock()
        mock_ffmpeg_proc = Mock()

        mock_popen.side_effect = [mock_yt_proc, mock_ffmpeg_proc]

        # Call function
        result = start_youtube_stream(
            "test123", skip_transcription=False, broadcaster=mock_broadcaster
        )

        # Verify ffmpeg command uses tee for dual output
        ffmpeg_cmd_call = mock_popen.call_args_list[1]
        ffmpeg_cmd = ffmpeg_cmd_call[0][0]
        assert "ffmpeg" in ffmpeg_cmd
        assert "-f" in ffmpeg_cmd
        assert "tee" in ffmpeg_cmd
        assert any("[f=mp3]pipe:1|[f=mp3]" in arg for arg in ffmpeg_cmd)

        # Verify logging
        assert mock_logger.info.called
        log_calls = [call[0][0] for call in mock_logger.info.call_args_list]
        assert any("Saving audio to" in msg for msg in log_calls)

        # Verify broadcaster was started
        mock_broadcaster.start_broadcasting.assert_called_once()

        # Verify return value
        assert result == mock_ffmpeg_proc

    @patch("services.streaming.subprocess.Popen")
    @patch("services.streaming.get_audio_cache")
    @patch("services.streaming.config")
    @patch("services.streaming.os.path.exists")
    @patch("services.streaming.os.path.getsize")
    @patch("services.streaming.logger")
    def test_stream_with_file_size_logging(
        self,
        mock_logger,
        mock_getsize,
        mock_exists,
        mock_config_module,
        mock_get_cache,
        mock_popen,
        mock_broadcaster,
        mock_config,
        mock_audio_cache,
    ):
        """Test that file size is logged when transcription saves audio."""
        # Setup mocks
        mock_config_module.transcription_enabled = True
        mock_config_module.get_audio_path = mock_config.get_audio_path
        mock_get_cache.return_value = mock_audio_cache
        mock_exists.return_value = True
        mock_getsize.return_value = 5242880  # 5 MB

        # Mock subprocess processes
        mock_yt_proc = Mock()
        mock_yt_proc.stdout = Mock()
        mock_ffmpeg_proc = Mock()
        mock_popen.side_effect = [mock_yt_proc, mock_ffmpeg_proc]

        # Call function
        start_youtube_stream("test123", skip_transcription=False, broadcaster=mock_broadcaster)

        # Verify file size logging
        log_calls = [call[0][0] for call in mock_logger.info.call_args_list]
        assert any("Audio file saved:" in msg and "5.00 MB" in msg for msg in log_calls)

    @patch("services.streaming.subprocess.Popen")
    @patch("services.streaming.get_audio_cache")
    @patch("services.streaming.config")
    @patch("services.streaming.logger")
    def test_stream_from_cache(
        self,
        mock_logger,
        mock_config_module,
        mock_get_cache,
        mock_popen,
        mock_broadcaster,
        mock_config,
        mock_audio_cache,
    ):
        """Test streaming from cached file."""
        # Setup mocks - file exists in cache
        mock_audio_cache.check_file_exists = Mock(return_value=True)
        mock_config_module.transcription_enabled = False
        mock_config_module.get_audio_path = mock_config.get_audio_path
        mock_get_cache.return_value = mock_audio_cache

        # Mock subprocess process
        mock_ffmpeg_proc = Mock()
        mock_popen.return_value = mock_ffmpeg_proc

        # Call function
        result = start_youtube_stream(
            "test123", skip_transcription=False, broadcaster=mock_broadcaster
        )

        # Verify only ffmpeg was called (no yt-dlp)
        assert mock_popen.call_count == 1

        # Verify ffmpeg command for cached file
        ffmpeg_cmd_call = mock_popen.call_args_list[0]
        ffmpeg_cmd = ffmpeg_cmd_call[0][0]
        assert "ffmpeg" in ffmpeg_cmd
        assert "-re" in ffmpeg_cmd  # Rate limiting for cached files
        assert "-c:a" in ffmpeg_cmd
        assert "copy" in ffmpeg_cmd  # Should copy, not re-encode
        assert "/tmp/audio-test/test123.mp3" in ffmpeg_cmd

        # Verify logging
        log_calls = [call[0][0] for call in mock_logger.info.call_args_list]
        assert any("already in cache" in msg for msg in log_calls)

        # Verify broadcaster was started
        mock_broadcaster.start_broadcasting.assert_called_once_with(mock_ffmpeg_proc)

        # Verify return value
        assert result == mock_ffmpeg_proc

    @patch("services.streaming.subprocess.Popen")
    @patch("services.streaming.get_audio_cache")
    @patch("services.streaming.config")
    def test_stream_skip_transcription(
        self,
        mock_config_module,
        mock_get_cache,
        mock_popen,
        mock_broadcaster,
        mock_config,
        mock_audio_cache,
    ):
        """Test streaming with skip_transcription=True uses standard ffmpeg command."""
        # Setup mocks
        mock_config_module.transcription_enabled = True
        mock_config_module.get_audio_path = mock_config.get_audio_path
        mock_get_cache.return_value = mock_audio_cache

        # Mock subprocess processes
        mock_yt_proc = Mock()
        mock_yt_proc.stdout = Mock()
        mock_ffmpeg_proc = Mock()
        mock_popen.side_effect = [mock_yt_proc, mock_ffmpeg_proc]

        # Call function with skip_transcription=True
        result = start_youtube_stream(
            "test123", skip_transcription=True, broadcaster=mock_broadcaster
        )

        # Verify ffmpeg command does NOT use tee (since transcription is skipped)
        ffmpeg_cmd_call = mock_popen.call_args_list[1]
        ffmpeg_cmd = ffmpeg_cmd_call[0][0]
        assert "tee" not in ffmpeg_cmd
        assert "-f" in ffmpeg_cmd
        assert "mp3" in ffmpeg_cmd

        # Verify broadcaster was started
        mock_broadcaster.start_broadcasting.assert_called_once()

    @patch("services.streaming.subprocess.Popen")
    @patch("services.streaming.get_audio_cache")
    @patch("services.streaming.config")
    def test_subprocess_buffer_sizes(
        self,
        mock_config_module,
        mock_get_cache,
        mock_popen,
        mock_broadcaster,
        mock_config,
        mock_audio_cache,
    ):
        """Test that subprocess calls use large buffer sizes."""
        # Setup mocks
        mock_config_module.transcription_enabled = False
        mock_config_module.get_audio_path = mock_config.get_audio_path
        mock_get_cache.return_value = mock_audio_cache

        # Mock subprocess processes
        mock_yt_proc = Mock()
        mock_yt_proc.stdout = Mock()
        mock_ffmpeg_proc = Mock()
        mock_popen.side_effect = [mock_yt_proc, mock_ffmpeg_proc]

        # Call function
        start_youtube_stream("test123", skip_transcription=False, broadcaster=mock_broadcaster)

        # Verify yt-dlp uses large buffer
        yt_call_kwargs = mock_popen.call_args_list[0][1]
        assert yt_call_kwargs["bufsize"] == 64 * 1024 * 1024  # 64MB

        # Verify ffmpeg uses large buffer
        ffmpeg_call_kwargs = mock_popen.call_args_list[1][1]
        assert ffmpeg_call_kwargs["bufsize"] == 64 * 1024 * 1024  # 64MB
