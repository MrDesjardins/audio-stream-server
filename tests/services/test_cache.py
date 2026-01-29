"""Tests for cache service."""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, Mock
from services.cache import AudioCache, TranscriptionCache, get_audio_cache, get_transcript_cache


class TestAudioCache:
    """Tests for AudioCache class."""

    def test_audio_cache_initialization(self):
        """Test audio cache initializes correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AudioCache(cache_dir=tmpdir, max_files=5)

            assert cache.cache_dir == tmpdir
            assert cache.max_files == 5
            assert os.path.exists(tmpdir)

    def test_check_file_exists_true(self):
        """Test check_file_exists returns True when file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AudioCache(cache_dir=tmpdir)

            # Create a test file
            test_file = os.path.join(tmpdir, "test123.mp3")
            Path(test_file).touch()

            assert cache.check_file_exists("test123") is True

    def test_check_file_exists_false(self):
        """Test check_file_exists returns False when file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AudioCache(cache_dir=tmpdir)

            assert cache.check_file_exists("nonexistent") is False

    def test_cleanup_old_files_removes_excess(self):
        """Test cleanup removes files beyond max_files limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AudioCache(cache_dir=tmpdir, max_files=3)

            # Create 5 files with different modification times
            for i in range(5):
                filepath = os.path.join(tmpdir, f"video{i}.mp3")
                Path(filepath).touch()
                # Set modification time to ensure ordering
                mtime = time.time() - (5 - i) * 10  # Older files have lower numbers
                os.utime(filepath, (mtime, mtime))

            cache.cleanup_old_files()

            # Should only have 3 most recent files
            remaining_files = os.listdir(tmpdir)
            assert len(remaining_files) == 3

            # Verify newest files remain (video2, video3, video4)
            assert "video2.mp3" in remaining_files
            assert "video3.mp3" in remaining_files
            assert "video4.mp3" in remaining_files
            assert "video0.mp3" not in remaining_files
            assert "video1.mp3" not in remaining_files

    def test_cleanup_old_files_under_limit(self):
        """Test cleanup doesn't remove files when under limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AudioCache(cache_dir=tmpdir, max_files=10)

            # Create 3 files
            for i in range(3):
                Path(os.path.join(tmpdir, f"video{i}.mp3")).touch()

            cache.cleanup_old_files()

            # All files should remain
            assert len(os.listdir(tmpdir)) == 3

    def test_cleanup_old_files_handles_missing_dir(self):
        """Test cleanup handles missing directory gracefully."""
        cache = AudioCache(cache_dir="/nonexistent/path", max_files=5)

        # Should not raise
        cache.cleanup_old_files()

    def test_cleanup_old_files_ignores_non_mp3(self):
        """Test cleanup ignores non-mp3 files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AudioCache(cache_dir=tmpdir, max_files=2)

            # Create mp3 and non-mp3 files
            Path(os.path.join(tmpdir, "video1.mp3")).touch()
            Path(os.path.join(tmpdir, "video2.mp3")).touch()
            Path(os.path.join(tmpdir, "video3.mp3")).touch()
            Path(os.path.join(tmpdir, "readme.txt")).touch()
            Path(os.path.join(tmpdir, "config.json")).touch()

            cache.cleanup_old_files()

            # Should have 2 mp3 files + 2 non-mp3 files
            remaining = os.listdir(tmpdir)
            assert len(remaining) == 4
            assert "readme.txt" in remaining
            assert "config.json" in remaining


class TestTranscriptionCache:
    """Tests for TranscriptionCache class."""

    def test_transcript_cache_initialization(self):
        """Test transcript cache initializes correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = TranscriptionCache(cache_dir=tmpdir)

            assert cache.cache_dir == tmpdir
            assert os.path.exists(tmpdir)

    def test_get_cached_transcript_exists(self):
        """Test getting cached transcript that exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = TranscriptionCache(cache_dir=tmpdir)

            # Create a cached transcript
            video_id = "test123"
            transcript_text = "This is the cached transcript"
            cache_file = os.path.join(tmpdir, f"{video_id}.txt")

            with open(cache_file, "w") as f:
                f.write(transcript_text)

            result = cache.get_cached_transcript(video_id)

            assert result == transcript_text

    def test_get_cached_transcript_not_exists(self):
        """Test getting cached transcript that doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = TranscriptionCache(cache_dir=tmpdir)

            result = cache.get_cached_transcript("nonexistent")

            assert result is None

    def test_save_transcript(self):
        """Test saving transcript to cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = TranscriptionCache(cache_dir=tmpdir)

            video_id = "test123"
            transcript_text = "This is the transcript to save"

            cache.save_transcript(video_id, transcript_text)

            # Verify file was created
            cache_file = os.path.join(tmpdir, f"{video_id}.txt")
            assert os.path.exists(cache_file)

            with open(cache_file, "r") as f:
                content = f.read()

            assert content == transcript_text

    def test_save_transcript_creates_directory(self):
        """Test that save_transcript creates directory if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "nested", "cache")
            cache = TranscriptionCache(cache_dir=cache_dir)

            cache.save_transcript("test123", "content")

            assert os.path.exists(cache_dir)

    def test_get_cached_summary_exists(self):
        """Test getting cached summary that exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = TranscriptionCache(cache_dir=tmpdir)

            video_id = "test123"
            summary_text = "This is the cached summary"
            cache_file = os.path.join(tmpdir, f"{video_id}_summary.txt")

            with open(cache_file, "w") as f:
                f.write(summary_text)

            result = cache.get_cached_summary(video_id)

            assert result == summary_text

    def test_get_cached_summary_not_exists(self):
        """Test getting cached summary that doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = TranscriptionCache(cache_dir=tmpdir)

            result = cache.get_cached_summary("nonexistent")

            assert result is None

    def test_save_summary(self):
        """Test saving summary to cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = TranscriptionCache(cache_dir=tmpdir)

            video_id = "test123"
            summary_text = "This is the summary to save"

            cache.save_summary(video_id, summary_text)

            # Verify file was created
            cache_file = os.path.join(tmpdir, f"{video_id}_summary.txt")
            assert os.path.exists(cache_file)

            with open(cache_file, "r") as f:
                content = f.read()

            assert content == summary_text


class TestCacheGetters:
    """Tests for global cache getter functions."""

    @patch("services.cache.get_config")
    def test_get_audio_cache(self, mock_config):
        """Test get_audio_cache returns singleton."""
        config = Mock()
        config.temp_audio_dir = "/tmp/test-audio"
        mock_config.return_value = config

        # Clear module cache if exists
        import services.cache

        services.cache._audio_cache = None

        cache1 = get_audio_cache()
        cache2 = get_audio_cache()

        # Should return same instance
        assert cache1 is cache2
        assert isinstance(cache1, AudioCache)

    @patch("services.cache.get_config")
    def test_get_transcript_cache(self, mock_config):
        """Test get_transcript_cache returns singleton."""
        config = Mock()
        mock_config.return_value = config

        # Clear module cache if exists
        import services.cache

        services.cache._transcript_cache = None

        cache1 = get_transcript_cache()
        cache2 = get_transcript_cache()

        # Should return same instance
        assert cache1 is cache2
        assert isinstance(cache1, TranscriptionCache)
