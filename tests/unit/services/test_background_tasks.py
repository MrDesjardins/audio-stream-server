"""Tests for background tasks service."""

import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from services.background_tasks import (
    TranscriptionJob,
    JobStatus,
    TranscriptionQueue,
    TranscriptionWorker,
)


class TestTranscriptionJob:
    """Tests for TranscriptionJob class."""

    def test_job_initialization(self):
        """Test job initializes with correct defaults."""
        job = TranscriptionJob(video_id="test123", audio_path="/tmp/test.mp3")

        assert job.video_id == "test123"
        assert job.audio_path == "/tmp/test.mp3"
        assert job.status == JobStatus.PENDING
        assert job.error is None
        assert job.transcript is None
        assert job.summary is None
        assert job.trilium_note_id is None
        assert job.trilium_note_url is None


class TestJobStatus:
    """Tests for JobStatus enum."""

    def test_job_status_values(self):
        """Test all job status values exist."""
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.CHECKING_DEDUP.value == "checking_dedup"
        assert JobStatus.TRANSCRIBING.value == "transcribing"
        assert JobStatus.SUMMARIZING.value == "summarizing"
        assert JobStatus.POSTING.value == "posting"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.FAILED.value == "failed"
        assert JobStatus.SKIPPED.value == "skipped"


class TestTranscriptionQueue:
    """Tests for TranscriptionQueue class."""

    def test_queue_initialization(self):
        """Test queue initializes correctly."""
        queue = TranscriptionQueue()

        assert queue.jobs == {}
        assert queue.lock is not None
        assert queue.queue is not None

    def test_add_job(self):
        """Test adding a job to the queue."""
        queue = TranscriptionQueue()
        job = TranscriptionJob(video_id="test123", audio_path="/tmp/test.mp3")

        queue.add_job(job)

        assert "test123" in queue.jobs
        assert queue.jobs["test123"] == job

    def test_add_multiple_jobs(self):
        """Test adding multiple jobs."""
        queue = TranscriptionQueue()

        job1 = TranscriptionJob(video_id="test1", audio_path="/tmp/test1.mp3")
        job2 = TranscriptionJob(video_id="test2", audio_path="/tmp/test2.mp3")

        queue.add_job(job1)
        queue.add_job(job2)

        assert len(queue.jobs) == 2
        assert "test1" in queue.jobs
        assert "test2" in queue.jobs

    def test_get_job_status_exists(self):
        """Test getting status of existing job."""
        queue = TranscriptionQueue()
        job = TranscriptionJob(video_id="test123", audio_path="/tmp/test.mp3")

        queue.add_job(job)
        result = queue.get_job_status("test123")

        assert result == job

    def test_get_job_status_not_exists(self):
        """Test getting status of non-existent job."""
        queue = TranscriptionQueue()

        result = queue.get_job_status("nonexistent")

        assert result is None

    def test_update_job_status(self):
        """Test updating job status."""
        queue = TranscriptionQueue()
        job = TranscriptionJob(video_id="test123", audio_path="/tmp/test.mp3")

        queue.add_job(job)
        queue.update_job_status("test123", JobStatus.TRANSCRIBING)

        assert queue.jobs["test123"].status == JobStatus.TRANSCRIBING

    def test_update_job_status_with_error(self):
        """Test updating job status with error."""
        queue = TranscriptionQueue()
        job = TranscriptionJob(video_id="test123", audio_path="/tmp/test.mp3")

        queue.add_job(job)
        queue.update_job_status("test123", JobStatus.FAILED, error="Test error")

        assert queue.jobs["test123"].status == JobStatus.FAILED
        assert queue.jobs["test123"].error == "Test error"

    def test_update_job_status_nonexistent(self):
        """Test updating status of non-existent job."""
        queue = TranscriptionQueue()

        # Should not raise an error
        queue.update_job_status("nonexistent", JobStatus.TRANSCRIBING)

    def test_get_job_from_queue(self):
        """Test getting a job from the queue."""
        queue = TranscriptionQueue()
        job = TranscriptionJob(video_id="test123", audio_path="/tmp/test.mp3")

        queue.add_job(job)
        retrieved_job = queue.get_job(timeout=0.1)

        assert retrieved_job == job
        assert retrieved_job.video_id == "test123"

    def test_get_job_timeout(self):
        """Test getting job times out when queue is empty."""
        queue = TranscriptionQueue()

        retrieved_job = queue.get_job(timeout=0.1)

        assert retrieved_job is None

    def test_add_job_skips_active_duplicate(self):
        """Adding a job with same video_id as a non-terminal job is a no-op."""
        queue = TranscriptionQueue()
        job1 = TranscriptionJob(video_id="dup", audio_path="/tmp/dup.mp3")
        queue.add_job(job1)

        job2 = TranscriptionJob(video_id="dup", audio_path="/tmp/dup2.mp3")
        queue.add_job(job2)

        # Still the original job
        assert queue.jobs["dup"].audio_path == "/tmp/dup.mp3"

    def test_add_job_replaces_failed_job(self):
        """A failed job can be re-queued with a new job."""
        queue = TranscriptionQueue()
        job1 = TranscriptionJob(video_id="retry", audio_path="/tmp/retry.mp3")
        queue.add_job(job1)
        queue.update_job_status("retry", JobStatus.FAILED, error="network error")

        job2 = TranscriptionJob(video_id="retry", audio_path="/tmp/retry2.mp3")
        queue.add_job(job2)

        assert queue.jobs["retry"].audio_path == "/tmp/retry2.mp3"
        assert queue.jobs["retry"].status == JobStatus.PENDING

    def test_update_job_sets_completed_at_on_terminal_status(self):
        """completed_at timestamp is set for COMPLETED, FAILED, SKIPPED."""
        queue = TranscriptionQueue()
        job = TranscriptionJob(video_id="ts1", audio_path="/tmp/ts1.mp3")
        queue.add_job(job)

        assert job.completed_at is None
        queue.update_job_status("ts1", JobStatus.COMPLETED)
        assert queue.jobs["ts1"].completed_at is not None

    def test_update_job_no_timestamp_for_non_terminal(self):
        """completed_at is NOT set for non-terminal statuses."""
        queue = TranscriptionQueue()
        job = TranscriptionJob(video_id="ts2", audio_path="/tmp/ts2.mp3")
        queue.add_job(job)

        queue.update_job_status("ts2", JobStatus.TRANSCRIBING)
        assert queue.jobs["ts2"].completed_at is None

    def test_update_job_sets_trilium_fields(self):
        """Trilium note ID and URL are stored on status update."""
        queue = TranscriptionQueue()
        job = TranscriptionJob(video_id="trl", audio_path="/tmp/trl.mp3")
        queue.add_job(job)

        queue.update_job_status(
            "trl",
            JobStatus.COMPLETED,
            trilium_note_id="note123",
            trilium_note_url="http://trilium/note123",
        )

        assert queue.jobs["trl"].trilium_note_id == "note123"
        assert queue.jobs["trl"].trilium_note_url == "http://trilium/note123"

    def test_update_job_sets_transcript_and_summary(self):
        """Transcript and summary are stored on status update."""
        queue = TranscriptionQueue()
        job = TranscriptionJob(video_id="txt", audio_path="/tmp/txt.mp3")
        queue.add_job(job)

        queue.update_job_status("txt", JobStatus.TRANSCRIBING, transcript="Hello world")
        queue.update_job_status("txt", JobStatus.SUMMARIZING, summary="Summary here")

        assert queue.jobs["txt"].transcript == "Hello world"
        assert queue.jobs["txt"].summary == "Summary here"

    def test_cleanup_removes_old_completed_jobs(self):
        """Old completed jobs are removed by cleanup."""
        queue = TranscriptionQueue()
        queue.max_job_age_hours = 0  # Everything is immediately "old"

        job = TranscriptionJob(video_id="old", audio_path="/tmp/old.mp3")
        queue.add_job(job)
        # Set completed_at to the past
        queue.jobs["old"].completed_at = datetime.now(timezone.utc) - timedelta(hours=1)
        queue.jobs["old"].status = JobStatus.COMPLETED

        queue._cleanup_old_jobs()

        assert "old" not in queue.jobs

    def test_cleanup_keeps_recent_jobs(self):
        """Recently completed jobs are preserved."""
        queue = TranscriptionQueue()
        queue.max_job_age_hours = 24

        job = TranscriptionJob(video_id="recent", audio_path="/tmp/recent.mp3")
        queue.add_job(job)
        queue.jobs["recent"].completed_at = datetime.now(timezone.utc)
        queue.jobs["recent"].status = JobStatus.COMPLETED

        queue._cleanup_old_jobs()

        assert "recent" in queue.jobs

    def test_cleanup_keeps_pending_jobs(self):
        """Jobs without completed_at are never cleaned up."""
        queue = TranscriptionQueue()
        queue.max_job_age_hours = 0

        job = TranscriptionJob(video_id="pending", audio_path="/tmp/pending.mp3")
        queue.add_job(job)

        queue._cleanup_old_jobs()

        assert "pending" in queue.jobs


class TestTranscriptionWorker:
    """Tests for TranscriptionWorker."""

    def test_worker_init(self):
        """Worker initializes in stopped state."""
        queue = TranscriptionQueue()
        worker = TranscriptionWorker(queue)
        assert worker.running is False
        assert worker.thread is None

    def test_start_sets_running_and_creates_thread(self):
        """start() sets running flag and spawns daemon thread."""
        queue = TranscriptionQueue()
        worker = TranscriptionWorker(queue)

        with patch.object(worker, "_worker_loop"):
            worker.start()
            assert worker.running is True
            assert worker.thread is not None
            assert worker.thread.daemon is True
            worker.stop()

    def test_start_is_idempotent(self):
        """Calling start() twice doesn't create a second thread."""
        queue = TranscriptionQueue()
        worker = TranscriptionWorker(queue)

        with patch.object(worker, "_worker_loop"):
            worker.start()
            first_thread = worker.thread
            worker.start()  # Second call — should be no-op
            assert worker.thread is first_thread
            worker.stop()

    def test_stop_sets_running_false(self):
        """stop() sets running to False."""
        queue = TranscriptionQueue()
        worker = TranscriptionWorker(queue)
        worker.running = True
        worker.thread = Mock()

        worker.stop()

        assert worker.running is False


class TestWaitForFile:
    """Tests for TranscriptionWorker._wait_for_file."""

    def test_returns_true_when_file_ready(self):
        """Returns True immediately when file exists and not downloading."""
        queue = TranscriptionQueue()
        worker = TranscriptionWorker(queue)

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "vid.mp3")
            with open(audio_path, "w") as f:
                f.write("audio data")

            with patch(
                "services.streaming.is_download_in_progress", return_value=False
            ):
                result = worker._wait_for_file(audio_path, "vid", timeout=5)

        assert result is True

    def test_returns_false_on_timeout(self):
        """Returns False when file never appears within timeout."""
        queue = TranscriptionQueue()
        worker = TranscriptionWorker(queue)

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "missing.mp3")

            with patch(
                "services.streaming.is_download_in_progress", return_value=False
            ):
                result = worker._wait_for_file(audio_path, "missing", timeout=1)

        assert result is False

    def test_waits_while_downloading(self):
        """Keeps polling while marker file exists, succeeds after marker removed."""
        queue = TranscriptionQueue()
        worker = TranscriptionWorker(queue)

        call_count = [0]

        def fake_in_progress(vid):
            call_count[0] += 1
            return call_count[0] < 2  # False on second call

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "wait_vid.mp3")
            with open(audio_path, "w") as f:
                f.write("data")

            with patch(
                "services.streaming.is_download_in_progress",
                side_effect=fake_in_progress,
            ):
                result = worker._wait_for_file(audio_path, "wait_vid", timeout=5)

        assert result is True
        assert call_count[0] >= 2

    def test_returns_false_for_zero_byte_file(self):
        """A zero-byte file is not considered ready."""
        queue = TranscriptionQueue()
        worker = TranscriptionWorker(queue)

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "empty.mp3")
            open(audio_path, "w").close()  # 0 bytes

            with patch(
                "services.streaming.is_download_in_progress", return_value=False
            ):
                result = worker._wait_for_file(audio_path, "empty", timeout=1)

        assert result is False


class TestProcessJob:
    """Tests for TranscriptionWorker._process_job."""

    def _make_worker(self):
        queue = TranscriptionQueue()
        return TranscriptionWorker(queue), queue

    def test_skips_when_already_in_trilium(self):
        """Job is marked SKIPPED when video already exists in Trilium."""
        worker, queue = self._make_worker()
        job = TranscriptionJob(video_id="exists", audio_path="/tmp/exists.mp3")
        queue.add_job(job)

        check_fn = Mock(return_value={"noteId": "n1", "url": "http://trilium/n1"})

        with patch.object(worker, "_wait_for_file", return_value=True):
            worker._process_job(job, check_fn, Mock(), Mock(), Mock())

        assert queue.jobs["exists"].status == JobStatus.SKIPPED
        assert queue.jobs["exists"].trilium_note_id == "n1"

    def test_full_pipeline_success(self):
        """Full transcribe -> summarize -> post pipeline completes."""
        worker, queue = self._make_worker()
        job = TranscriptionJob(video_id="full", audio_path="/tmp/full.mp3")
        queue.add_job(job)

        check_fn = Mock(return_value=None)  # Not in Trilium
        transcribe_fn = Mock(return_value="Transcript text")
        summarize_fn = Mock(return_value="Summary text")
        post_fn = Mock(return_value={"noteId": "new1", "url": "http://trilium/new1"})

        with (
            patch.object(worker, "_wait_for_file", return_value=True),
            patch(
                "services.background_tasks.get_transcript_cache"
            ) as mock_cache_getter,
        ):
            mock_cache = Mock()
            mock_cache.get_cached = Mock(return_value=None)
            mock_cache_getter.return_value = mock_cache

            worker._process_job(job, check_fn, transcribe_fn, summarize_fn, post_fn)

        assert queue.jobs["full"].status == JobStatus.COMPLETED
        assert queue.jobs["full"].trilium_note_id == "new1"
        transcribe_fn.assert_called_once_with("/tmp/full.mp3", retries=3)
        summarize_fn.assert_called_once_with("Transcript text", "full")
        post_fn.assert_called_once_with("full", "Transcript text", "Summary text")

    def test_uses_cached_transcript(self):
        """Cached transcript is used instead of calling Whisper."""
        worker, queue = self._make_worker()
        job = TranscriptionJob(video_id="cached", audio_path="/tmp/cached.mp3")
        queue.add_job(job)

        check_fn = Mock(return_value=None)
        transcribe_fn = Mock()
        summarize_fn = Mock(return_value="Summary")
        post_fn = Mock(return_value={"noteId": "n2", "url": "http://trilium/n2"})

        with (
            patch.object(worker, "_wait_for_file", return_value=True),
            patch(
                "services.background_tasks.get_transcript_cache"
            ) as mock_cache_getter,
        ):
            mock_cache = Mock()
            mock_cache.get_cached = Mock(
                return_value={"transcript": "Cached transcript", "summary": None}
            )
            mock_cache_getter.return_value = mock_cache

            worker._process_job(job, check_fn, transcribe_fn, summarize_fn, post_fn)

        transcribe_fn.assert_not_called()
        summarize_fn.assert_called_once_with("Cached transcript", "cached")

    def test_uses_cached_summary(self):
        """Cached summary is used instead of calling summarizer."""
        worker, queue = self._make_worker()
        job = TranscriptionJob(video_id="csummary", audio_path="/tmp/csummary.mp3")
        queue.add_job(job)

        check_fn = Mock(return_value=None)
        transcribe_fn = Mock()
        summarize_fn = Mock()
        post_fn = Mock(return_value={"noteId": "n3", "url": "http://trilium/n3"})

        with (
            patch.object(worker, "_wait_for_file", return_value=True),
            patch(
                "services.background_tasks.get_transcript_cache"
            ) as mock_cache_getter,
        ):
            mock_cache = Mock()
            mock_cache.get_cached = Mock(
                return_value={
                    "transcript": "Full transcript",
                    "summary": "Cached summary",
                }
            )
            mock_cache_getter.return_value = mock_cache

            worker._process_job(job, check_fn, transcribe_fn, summarize_fn, post_fn)

        transcribe_fn.assert_not_called()
        summarize_fn.assert_not_called()
        post_fn.assert_called_once_with("csummary", "Full transcript", "Cached summary")

    def test_fails_on_download_timeout(self):
        """Job is marked FAILED when audio file never becomes ready."""
        worker, queue = self._make_worker()
        job = TranscriptionJob(video_id="timeout", audio_path="/tmp/timeout.mp3")
        queue.add_job(job)

        with patch.object(worker, "_wait_for_file", return_value=False):
            worker._process_job(job, Mock(), Mock(), Mock(), Mock())

        assert queue.jobs["timeout"].status == JobStatus.FAILED
        assert "timeout" in queue.jobs["timeout"].error.lower()

    def test_fails_on_transcription_error(self):
        """Job is marked FAILED when transcription raises."""
        worker, queue = self._make_worker()
        job = TranscriptionJob(video_id="terr", audio_path="/tmp/terr.mp3")
        queue.add_job(job)

        check_fn = Mock(return_value=None)
        transcribe_fn = Mock(side_effect=Exception("Whisper API error"))

        with (
            patch.object(worker, "_wait_for_file", return_value=True),
            patch(
                "services.background_tasks.get_transcript_cache"
            ) as mock_cache_getter,
        ):
            mock_cache = Mock()
            mock_cache.get_cached = Mock(return_value=None)
            mock_cache_getter.return_value = mock_cache

            worker._process_job(job, check_fn, transcribe_fn, Mock(), Mock())

        assert queue.jobs["terr"].status == JobStatus.FAILED
        assert "Whisper API error" in queue.jobs["terr"].error


class TestAsyncAudioCleanup:
    """Tests for async audio cleanup feature (2.2)."""

    def test_cleanup_runs_in_separate_thread(self):
        """Cleanup should run in separate thread and not block."""
        worker = TranscriptionWorker(TranscriptionQueue())

        # Mock the get_audio_cache to track if cleanup was called
        cleanup_called = []

        def mock_cleanup():
            cleanup_called.append(True)

        with patch("services.background_tasks.get_audio_cache") as mock_cache_getter:
            mock_cache = Mock()
            mock_cache.cleanup_old_files = mock_cleanup
            mock_cache_getter.return_value = mock_cache

            # Call async cleanup
            worker._cleanup_audio_async()

            # Give thread time to start and run
            import time

            time.sleep(0.1)

            # Verify cleanup was called
            assert len(cleanup_called) == 1

    def test_cleanup_errors_dont_crash_worker(self):
        """Cleanup errors should be logged but not crash the worker."""
        worker = TranscriptionWorker(TranscriptionQueue())

        with patch("services.background_tasks.get_audio_cache") as mock_cache_getter:
            mock_cache = Mock()
            mock_cache.cleanup_old_files = Mock(side_effect=Exception("Cleanup error"))
            mock_cache_getter.return_value = mock_cache

            # Should not raise exception
            worker._cleanup_audio_async()

            # Give thread time to run
            import time

            time.sleep(0.1)

            # Worker should still be fine
            assert worker is not None


class TestJobDeduplication:
    """Tests for enhanced job deduplication (2.3)."""

    def test_add_job_returns_true_for_new_job(self):
        """add_job should return True when adding a new job."""
        queue = TranscriptionQueue()
        job = TranscriptionJob(video_id="new_video", audio_path="/tmp/new.mp3")

        result = queue.add_job(job)

        assert result is True
        assert "new_video" in queue.jobs

    def test_add_job_returns_false_for_duplicate(self):
        """add_job should return False when job already active."""
        queue = TranscriptionQueue()
        job1 = TranscriptionJob(video_id="dup", audio_path="/tmp/dup.mp3")
        job2 = TranscriptionJob(video_id="dup", audio_path="/tmp/dup.mp3")

        result1 = queue.add_job(job1)
        result2 = queue.add_job(job2)

        assert result1 is True
        assert result2 is False

    def test_add_job_allows_completed_requeue(self):
        """add_job should allow re-adding completed jobs (Trilium will dedupe)."""
        queue = TranscriptionQueue()
        job1 = TranscriptionJob(video_id="completed", audio_path="/tmp/completed.mp3")

        # Add and complete job
        queue.add_job(job1)
        queue.update_job_status("completed", JobStatus.COMPLETED)

        # Try to add again - should succeed (Trilium check will handle dedup)
        job2 = TranscriptionJob(video_id="completed", audio_path="/tmp/completed.mp3")
        result = queue.add_job(job2)

        assert result is True

    def test_should_skip_transcription_for_active_job(self):
        """should_skip_transcription returns True for active jobs."""
        queue = TranscriptionQueue()
        job = TranscriptionJob(video_id="active", audio_path="/tmp/active.mp3")
        queue.add_job(job)

        should_skip, reason = queue.should_skip_transcription("active")

        assert should_skip is True
        assert "already queued" in reason.lower()

    def test_should_skip_transcription_allows_completed(self):
        """should_skip_transcription allows completed jobs (Trilium will dedupe)."""
        queue = TranscriptionQueue()
        job = TranscriptionJob(video_id="completed", audio_path="/tmp/completed.mp3")
        queue.add_job(job)
        queue.update_job_status("completed", JobStatus.COMPLETED)

        should_skip, reason = queue.should_skip_transcription("completed")

        assert should_skip is False
        assert reason == ""

    def test_should_skip_transcription_allows_new_job(self):
        """should_skip_transcription returns False for new videos."""
        queue = TranscriptionQueue()

        should_skip, reason = queue.should_skip_transcription("new_video")

        assert should_skip is False
        assert reason == ""
