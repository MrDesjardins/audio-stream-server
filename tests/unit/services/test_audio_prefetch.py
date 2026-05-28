"""Tests for background audio prefetching."""

from unittest.mock import Mock, patch

from services.audio_prefetch import AudioPrefetcher


def create_prefetcher_without_worker() -> AudioPrefetcher:
    """Create a prefetcher whose worker thread exits immediately."""
    with patch.object(AudioPrefetcher, "_worker_loop", return_value=None):
        return AudioPrefetcher()


class TestAudioPrefetcher:
    """Tests for AudioPrefetcher."""

    @patch("services.audio_prefetch.is_download_in_progress", return_value=False)
    @patch("services.audio_prefetch.get_audio_cache")
    def test_enqueue_returns_cached_when_file_exists(
        self, mock_get_cache, mock_in_progress
    ):
        """Cached videos are not enqueued."""
        cache = Mock()
        cache.check_file_exists.return_value = True
        mock_get_cache.return_value = cache
        prefetcher = create_prefetcher_without_worker()

        assert prefetcher.enqueue("vid1") == "cached"
        assert prefetcher._queue.empty()

    @patch("services.audio_prefetch.is_download_in_progress", return_value=True)
    @patch("services.audio_prefetch.get_audio_cache")
    def test_enqueue_returns_downloading_when_marker_exists(
        self, mock_get_cache, mock_in_progress
    ):
        """Existing download markers prevent duplicate work."""
        cache = Mock()
        cache.check_file_exists.return_value = False
        mock_get_cache.return_value = cache
        prefetcher = create_prefetcher_without_worker()

        assert prefetcher.enqueue("vid1") == "downloading"
        assert prefetcher._queue.empty()

    @patch("services.audio_prefetch.is_download_in_progress", return_value=False)
    @patch("services.audio_prefetch.get_audio_cache")
    def test_enqueue_deduplicates_queued_items(self, mock_get_cache, mock_in_progress):
        """The same video is only queued once."""
        cache = Mock()
        cache.check_file_exists.return_value = False
        mock_get_cache.return_value = cache
        prefetcher = create_prefetcher_without_worker()

        assert prefetcher.enqueue("vid1") == "queued"
        assert prefetcher.enqueue("vid1") == "queued"
        assert prefetcher._queue.qsize() == 1

    @patch("services.audio_prefetch.finish_youtube_download")
    @patch("services.audio_prefetch.start_youtube_download")
    @patch("services.audio_prefetch.is_download_in_progress", return_value=False)
    @patch("services.audio_prefetch.get_audio_cache")
    def test_prefetch_records_failed_status_on_download_failure(
        self, mock_get_cache, mock_in_progress, mock_start, mock_finish
    ):
        """A failed yt-dlp process is reflected in status."""
        cache = Mock()
        cache.check_file_exists.return_value = False
        mock_get_cache.return_value = cache
        proc = Mock()
        proc.returncode = 1
        mock_start.return_value = proc
        prefetcher = create_prefetcher_without_worker()

        prefetcher._prefetch("vid1")

        proc.wait.assert_called_once()
        mock_finish.assert_called_once_with("vid1", 1)
        assert prefetcher.get_status("vid1") == "failed"

    @patch("services.audio_prefetch.finish_youtube_download")
    @patch("services.audio_prefetch.start_youtube_download")
    @patch("services.audio_prefetch.is_download_in_progress", return_value=False)
    @patch("services.audio_prefetch.get_audio_cache")
    def test_prefetch_clears_failed_status_on_success(
        self, mock_get_cache, mock_in_progress, mock_start, mock_finish
    ):
        """A successful download reports cached once the file exists."""
        cache = Mock()
        cache.check_file_exists.side_effect = [False, True, True]
        mock_get_cache.return_value = cache
        proc = Mock()
        proc.returncode = 0
        mock_start.return_value = proc
        prefetcher = create_prefetcher_without_worker()
        prefetcher._failed_video_ids.add("vid1")

        prefetcher._prefetch("vid1")

        assert prefetcher.get_status("vid1") == "cached"
