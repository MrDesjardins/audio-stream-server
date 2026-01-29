"""Tests for cache thread safety and concurrent access."""

import pytest
import threading
import json
import tempfile
from services.cache import TranscriptionCache, get_transcript_cache, get_audio_cache


class TestTranscriptionCacheConcurrency:
    """Test TranscriptionCache thread safety."""

    @pytest.fixture
    def cache_dir(self):
        """Create a temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def cache(self, cache_dir):
        """Create a cache instance."""
        return TranscriptionCache(cache_dir)

    def test_concurrent_writes_to_same_video(self, cache):
        """Test 100 concurrent writes to same video don't corrupt JSON."""
        video_id = "test_video"
        num_threads = 100
        errors = []

        def write_transcript(thread_num):
            try:
                cache.save_transcript(video_id, f"Transcript from thread {thread_num}")
            except Exception as e:
                errors.append(e)

        def write_summary(thread_num):
            try:
                cache.save_summary(video_id, f"Summary from thread {thread_num}")
            except Exception as e:
                errors.append(e)

        # Create threads that alternate between saving transcripts and summaries
        threads = []
        for i in range(num_threads):
            if i % 2 == 0:
                t = threading.Thread(target=write_transcript, args=(i,))
            else:
                t = threading.Thread(target=write_summary, args=(i,))
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join()

        # Should have no errors
        assert len(errors) == 0, f"Concurrent writes produced errors: {errors}"

        # Verify the cache file is valid JSON
        cached = cache.get_cached(video_id)
        assert cached is not None
        assert "transcript" in cached
        assert "summary" in cached

        # Verify the file itself is valid JSON
        cache_file = cache._get_cache_path(video_id)
        with open(cache_file, "r") as f:
            data = json.load(f)  # Should not raise JSONDecodeError
            assert "transcript" in data
            assert "summary" in data
            assert "transcript_timestamp" in data
            assert "summary_timestamp" in data

    def test_concurrent_writes_to_different_videos(self, cache):
        """Test concurrent writes to different videos work correctly."""
        num_threads = 50
        errors = []

        def write_data(video_num):
            try:
                video_id = f"video_{video_num}"
                cache.save_transcript(video_id, f"Transcript {video_num}")
                cache.save_summary(video_id, f"Summary {video_num}")
            except Exception as e:
                errors.append(e)

        # Create threads
        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=write_data, args=(i,))
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join()

        # Should have no errors
        assert len(errors) == 0, f"Concurrent writes produced errors: {errors}"

        # Verify all videos have valid data
        for i in range(num_threads):
            video_id = f"video_{i}"
            cached = cache.get_cached(video_id)
            assert cached is not None
            assert cached["transcript"] == f"Transcript {i}"
            assert cached["summary"] == f"Summary {i}"


class TestSingletonThreadSafety:
    """Test that singleton getters are thread-safe."""

    def test_concurrent_get_transcript_cache_creates_one_instance(self):
        """Test 100 concurrent calls to get_transcript_cache create only one instance."""
        # Reset global instance
        import services.cache as cache_module

        cache_module._transcript_cache = None

        instances = []

        def get_cache():
            instances.append(get_transcript_cache())

        # Create 100 threads
        threads = []
        for _ in range(100):
            t = threading.Thread(target=get_cache)
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join()

        # All instances should be the same object
        assert len(instances) == 100
        first_instance = instances[0]
        for instance in instances:
            assert instance is first_instance, "Multiple instances created"

    def test_concurrent_get_audio_cache_creates_one_instance(self):
        """Test 100 concurrent calls to get_audio_cache create only one instance."""
        # Reset global instance
        import services.cache as cache_module

        cache_module._audio_cache = None

        instances = []

        def get_cache():
            instances.append(get_audio_cache())

        # Create 100 threads
        threads = []
        for _ in range(100):
            t = threading.Thread(target=get_cache)
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join()

        # All instances should be the same object
        assert len(instances) == 100
        first_instance = instances[0]
        for instance in instances:
            assert instance is first_instance, "Multiple instances created"

    def test_concurrent_get_config_creates_one_instance(self):
        """Test 100 concurrent calls to get_config create only one instance."""
        from config import get_config
        import config as config_module

        # Reset global instance
        config_module.config = None

        instances = []

        def get_cfg():
            instances.append(get_config())

        # Create 100 threads
        threads = []
        for _ in range(100):
            t = threading.Thread(target=get_cfg)
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join()

        # All instances should be the same object
        assert len(instances) == 100
        first_instance = instances[0]
        for instance in instances:
            assert instance is first_instance, "Multiple instances created"
