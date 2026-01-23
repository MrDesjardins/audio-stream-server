"""Tests for background tasks service."""
from unittest.mock import Mock, patch, MagicMock
import pytest
from services.background_tasks import (
    TranscriptionJob,
    JobStatus,
    TranscriptionQueue,
    get_transcription_queue
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
