"""Tests for streaming service (yt-dlp download pipeline)."""

import os
import tempfile
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def temp_audio_dir():
    """Temporary directory for audio files during tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_config(temp_audio_dir):
    """Mock config with temp audio directory."""
    config = Mock()
    config.temp_audio_dir = temp_audio_dir
    config.audio_quality = 6
    config.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
    return config


@pytest.fixture
def mock_audio_cache():
    """Mock audio cache."""
    cache = Mock()
    cache.check_file_exists = Mock(return_value=False)
    return cache


class TestGetDownloadMarker:
    """Tests for _get_download_marker."""

    @patch("services.streaming.config")
    def test_returns_marker_path(self, mock_cfg, temp_audio_dir):
        """Test marker path uses video_id.downloading in audio dir."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        from services.streaming import _get_download_marker

        result = _get_download_marker("abc123")
        assert result == os.path.join(temp_audio_dir, "abc123.downloading")

    @patch("services.streaming.config")
    def test_marker_path_for_different_ids(self, mock_cfg, temp_audio_dir):
        """Each video ID gets its own marker path."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        from services.streaming import _get_download_marker

        path1 = _get_download_marker("video1")
        path2 = _get_download_marker("video2")
        assert path1 != path2
        assert "video1.downloading" in path1
        assert "video2.downloading" in path2


class TestIsDownloadInProgress:
    """Tests for is_download_in_progress."""

    @patch("services.streaming.config")
    def test_returns_true_when_marker_exists(self, mock_cfg, temp_audio_dir):
        """Returns True when .downloading marker file exists."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        marker = os.path.join(temp_audio_dir, "vid1.downloading")
        open(marker, "w").close()

        from services.streaming import is_download_in_progress

        assert is_download_in_progress("vid1") is True

    @patch("services.streaming.config")
    def test_returns_false_when_marker_missing(self, mock_cfg, temp_audio_dir):
        """Returns False when no marker file exists."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        from services.streaming import is_download_in_progress

        assert is_download_in_progress("vid1") is False


class TestStartYoutubeDownload:
    """Tests for start_youtube_download."""

    @patch("services.streaming.subprocess.Popen")
    @patch("services.streaming.get_audio_cache")
    @patch("services.streaming.config")
    def test_returns_none_when_cached(
        self, mock_cfg, mock_get_cache, mock_popen, temp_audio_dir
    ):
        """Returns (None, video_id) when file already exists in cache."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        cache = Mock()
        cache.check_file_exists = Mock(return_value=True)
        mock_get_cache.return_value = cache

        from services.streaming import start_youtube_download

        proc, vid = start_youtube_download("cached_vid", skip_transcription=False)

        assert proc is None
        assert vid == "cached_vid"
        mock_popen.assert_not_called()

    @patch("services.streaming.subprocess.Popen")
    @patch("services.streaming.get_audio_cache")
    @patch("services.streaming.config")
    def test_creates_marker_file(
        self, mock_cfg, mock_get_cache, mock_popen, temp_audio_dir
    ):
        """Creates .downloading marker before starting yt-dlp."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.audio_quality = 4
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        cache = Mock()
        cache.check_file_exists = Mock(return_value=False)
        mock_get_cache.return_value = cache
        mock_popen.return_value = Mock()

        from services.streaming import start_youtube_download

        start_youtube_download("new_vid", skip_transcription=False)

        marker = os.path.join(temp_audio_dir, "new_vid.downloading")
        assert os.path.exists(marker)

    @patch("services.streaming.subprocess.Popen")
    @patch("services.streaming.get_audio_cache")
    @patch("services.streaming.config")
    def test_returns_process_on_success(
        self, mock_cfg, mock_get_cache, mock_popen, temp_audio_dir
    ):
        """Returns (proc, video_id) when download starts successfully."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.audio_quality = 6
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        cache = Mock()
        cache.check_file_exists = Mock(return_value=False)
        mock_get_cache.return_value = cache
        fake_proc = Mock()
        mock_popen.return_value = fake_proc

        from services.streaming import start_youtube_download

        proc, vid = start_youtube_download("test_vid", skip_transcription=True)

        assert proc is fake_proc
        assert vid == "test_vid"

    @patch("services.streaming.subprocess.Popen")
    @patch("services.streaming.get_audio_cache")
    @patch("services.streaming.config")
    def test_passes_audio_quality_to_yt_dlp(
        self, mock_cfg, mock_get_cache, mock_popen, temp_audio_dir
    ):
        """Audio quality from config is passed to yt-dlp command."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.audio_quality = 3
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        cache = Mock()
        cache.check_file_exists = Mock(return_value=False)
        mock_get_cache.return_value = cache
        mock_popen.return_value = Mock()

        from services.streaming import start_youtube_download

        start_youtube_download("q_vid", skip_transcription=False)

        cmd = mock_popen.call_args[0][0]
        quality_idx = cmd.index("--audio-quality")
        assert cmd[quality_idx + 1] == "3"

    @patch("services.streaming.subprocess.Popen")
    @patch("services.streaming.get_audio_cache")
    @patch("services.streaming.config")
    def test_output_path_has_no_extension(
        self, mock_cfg, mock_get_cache, mock_popen, temp_audio_dir
    ):
        """yt-dlp -o path must NOT include .mp3 (yt-dlp appends it)."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.audio_quality = 4
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        cache = Mock()
        cache.check_file_exists = Mock(return_value=False)
        mock_get_cache.return_value = cache
        mock_popen.return_value = Mock()

        from services.streaming import start_youtube_download

        start_youtube_download("ext_vid", skip_transcription=False)

        cmd = mock_popen.call_args[0][0]
        output_idx = cmd.index("-o")
        output_path = cmd[output_idx + 1]
        assert not output_path.endswith(
            ".mp3"
        ), "Output path must not include .mp3 extension"

    @patch("services.streaming.subprocess.Popen")
    @patch("services.streaming.get_audio_cache")
    @patch("services.streaming.config")
    def test_cleans_marker_on_popen_exception(
        self, mock_cfg, mock_get_cache, mock_popen, temp_audio_dir
    ):
        """Marker file is cleaned up if Popen raises an exception."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.audio_quality = 4
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        cache = Mock()
        cache.check_file_exists = Mock(return_value=False)
        mock_get_cache.return_value = cache
        mock_popen.side_effect = OSError("yt-dlp not found")

        from services.streaming import start_youtube_download

        proc, vid = start_youtube_download("fail_vid", skip_transcription=False)

        assert proc is None
        assert vid == "fail_vid"
        marker = os.path.join(temp_audio_dir, "fail_vid.downloading")
        assert not os.path.exists(marker)

    @patch("services.streaming.subprocess.Popen")
    @patch("services.streaming.get_audio_cache")
    @patch("services.streaming.config")
    def test_stderr_written_to_file_not_pipe(
        self, mock_cfg, mock_get_cache, mock_popen, temp_audio_dir
    ):
        """stderr is redirected to a file, not subprocess.PIPE."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.audio_quality = 4
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        cache = Mock()
        cache.check_file_exists = Mock(return_value=False)
        mock_get_cache.return_value = cache
        mock_popen.return_value = Mock()

        from services.streaming import start_youtube_download

        start_youtube_download("stderr_vid", skip_transcription=False)

        kwargs = mock_popen.call_args[1]
        # stderr should be a file object, not subprocess.PIPE
        import subprocess

        assert kwargs["stderr"] is not subprocess.PIPE
        assert kwargs["stdout"] == subprocess.DEVNULL


class TestFinishYoutubeDownload:
    """Tests for finish_youtube_download."""

    @patch("services.streaming.config")
    def test_removes_marker_on_success(self, mock_cfg, temp_audio_dir):
        """Marker file is removed after successful download."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")

        # Create marker and audio file
        marker = os.path.join(temp_audio_dir, "done_vid.downloading")
        audio = os.path.join(temp_audio_dir, "done_vid.mp3")
        open(marker, "w").close()
        with open(audio, "w") as f:
            f.write("fake audio data")

        from services.streaming import finish_youtube_download

        finish_youtube_download("done_vid", returncode=0)

        assert not os.path.exists(marker)

    @patch("services.streaming.config")
    def test_removes_marker_on_failure(self, mock_cfg, temp_audio_dir):
        """Marker file is removed even on failed download."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")

        marker = os.path.join(temp_audio_dir, "fail_vid.downloading")
        open(marker, "w").close()

        from services.streaming import finish_youtube_download

        finish_youtube_download("fail_vid", returncode=1)

        assert not os.path.exists(marker)

    @patch("services.streaming.config")
    def test_cleans_partial_file_on_failure(self, mock_cfg, temp_audio_dir):
        """Partial MP3 file is deleted when download fails."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")

        audio = os.path.join(temp_audio_dir, "partial_vid.mp3")
        marker = os.path.join(temp_audio_dir, "partial_vid.downloading")
        with open(audio, "w") as f:
            f.write("partial data")
        open(marker, "w").close()

        from services.streaming import finish_youtube_download

        finish_youtube_download("partial_vid", returncode=137)

        assert not os.path.exists(audio)

    @patch("services.streaming.config")
    def test_keeps_file_on_success(self, mock_cfg, temp_audio_dir):
        """MP3 file is preserved when download succeeds."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")

        audio = os.path.join(temp_audio_dir, "good_vid.mp3")
        marker = os.path.join(temp_audio_dir, "good_vid.downloading")
        with open(audio, "w") as f:
            f.write("complete audio data")
        open(marker, "w").close()

        from services.streaming import finish_youtube_download

        finish_youtube_download("good_vid", returncode=0)

        assert os.path.exists(audio)

    @patch("services.streaming.config")
    def test_cleans_stderr_file(self, mock_cfg, temp_audio_dir):
        """Stderr log file is cleaned up after finish."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")

        stderr_file = os.path.join(temp_audio_dir, "err_vid.mp3.err")
        with open(stderr_file, "w") as f:
            f.write("some yt-dlp output")

        from services.streaming import finish_youtube_download

        finish_youtube_download("err_vid", returncode=0)

        assert not os.path.exists(stderr_file)

    @patch("services.streaming.config")
    def test_logs_error_output_on_failure(self, mock_cfg, temp_audio_dir):
        """Error output from stderr is logged when download fails."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")

        stderr_file = os.path.join(temp_audio_dir, "log_vid.mp3.err")
        with open(stderr_file, "w") as f:
            f.write("ERROR: Forbidden")

        from services.streaming import finish_youtube_download

        # Should not raise — just logs
        finish_youtube_download("log_vid", returncode=1)

    @patch("services.streaming.config")
    def test_no_error_when_marker_already_gone(self, mock_cfg, temp_audio_dir):
        """No crash if marker was already removed (idempotent)."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")

        from services.streaming import finish_youtube_download

        # Should not raise even though marker doesn't exist
        finish_youtube_download("no_marker_vid", returncode=0)

    @patch("services.streaming.config")
    def test_calls_cleanup_on_success(self, mock_cfg, temp_audio_dir):
        """Cleanup should be called after successful download."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")

        # Create a successful audio file
        audio_path = os.path.join(temp_audio_dir, "cleanup_vid.mp3")
        with open(audio_path, "wb") as f:
            f.write(b"audio data")

        from services.streaming import finish_youtube_download

        with patch("services.cache.get_audio_cache") as mock_cache_getter:
            mock_cache = Mock()
            mock_cache.cleanup_old_files = Mock()
            mock_cache_getter.return_value = mock_cache

            finish_youtube_download("cleanup_vid", returncode=0)

            # Verify cleanup was called
            mock_cache_getter.assert_called_once()
            mock_cache.cleanup_old_files.assert_called_once()

    @patch("services.streaming.config")
    def test_no_cleanup_on_failure(self, mock_cfg, temp_audio_dir):
        """Cleanup should NOT be called when download fails."""
        mock_cfg.temp_audio_dir = temp_audio_dir
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")

        from services.streaming import finish_youtube_download

        with patch("services.cache.get_audio_cache") as mock_cache_getter:
            mock_cache = Mock()
            mock_cache.cleanup_old_files = Mock()
            mock_cache_getter.return_value = mock_cache

            finish_youtube_download("fail_vid", returncode=1)

            # Verify cleanup was NOT called (file failed)
            mock_cache_getter.assert_not_called()
            mock_cache.cleanup_old_files.assert_not_called()
