"""Tests for transcription routes."""
from unittest.mock import Mock, patch
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from routes.transcription import router
from services.background_tasks import TranscriptionJob, JobStatus


@pytest.fixture
def client():
    """FastAPI test client for transcription router."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestGetTranscriptionStatus:
    """Tests for /transcription/status/{video_id} endpoint."""

    @patch('routes.transcription.config')
    def test_get_status_transcription_disabled(self, mock_config, client):
        """Test status when transcription is disabled."""
        mock_config.transcription_enabled = False

        response = client.get("/transcription/status/test123")

        assert response.status_code == 400
        assert "Transcription not enabled" in response.json()["detail"]

    @patch('routes.transcription.get_transcription_queue')
    @patch('routes.transcription.config')
    def test_get_status_job_not_found(self, mock_config, mock_get_queue, client):
        """Test status when job not found."""
        mock_config.transcription_enabled = True

        mock_queue = Mock()
        mock_queue.get_job_status.return_value = None
        mock_get_queue.return_value = mock_queue

        response = client.get("/transcription/status/test123")

        assert response.status_code == 200
        data = response.json()
        assert data["video_id"] == "test123"
        assert data["status"] == "not_found"
        assert data["error"] is None

    @patch('routes.transcription.get_transcription_queue')
    @patch('routes.transcription.config')
    def test_get_status_job_pending(self, mock_config, mock_get_queue, client):
        """Test status for pending job."""
        mock_config.transcription_enabled = True

        mock_job = TranscriptionJob(video_id="test123", audio_path="/tmp/test.mp3")
        mock_job.status = JobStatus.PENDING

        mock_queue = Mock()
        mock_queue.get_job_status.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        response = client.get("/transcription/status/test123")

        assert response.status_code == 200
        data = response.json()
        assert data["video_id"] == "test123"
        assert data["status"] == "pending"

    @patch('routes.transcription.get_transcription_queue')
    @patch('routes.transcription.config')
    def test_get_status_job_completed(self, mock_config, mock_get_queue, client):
        """Test status for completed job."""
        mock_config.transcription_enabled = True

        mock_job = TranscriptionJob(video_id="test123", audio_path="/tmp/test.mp3")
        mock_job.status = JobStatus.COMPLETED
        mock_job.summary = "Test summary"
        mock_job.trilium_note_id = "note123"
        mock_job.trilium_note_url = "http://trilium/note123"

        mock_queue = Mock()
        mock_queue.get_job_status.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        response = client.get("/transcription/status/test123")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["summary"] == "Test summary"
        assert data["trilium_note_id"] == "note123"
        assert data["trilium_note_url"] == "http://trilium/note123"

    @patch('routes.transcription.get_transcription_queue')
    @patch('routes.transcription.config')
    def test_get_status_job_failed(self, mock_config, mock_get_queue, client):
        """Test status for failed job."""
        mock_config.transcription_enabled = True

        mock_job = TranscriptionJob(video_id="test123", audio_path="/tmp/test.mp3")
        mock_job.status = JobStatus.FAILED
        mock_job.error = "Transcription error"

        mock_queue = Mock()
        mock_queue.get_job_status.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        response = client.get("/transcription/status/test123")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["error"] == "Transcription error"

    @patch('routes.transcription.get_transcription_queue')
    @patch('routes.transcription.config')
    def test_get_status_error(self, mock_config, mock_get_queue, client):
        """Test status endpoint with error."""
        mock_config.transcription_enabled = True
        mock_get_queue.side_effect = Exception("Queue error")

        response = client.get("/transcription/status/test123")

        assert response.status_code == 500
        assert "Queue error" in response.json()["detail"]


class TestStartTranscription:
    """Tests for /transcription/start/{video_id} endpoint."""

    @patch('routes.transcription.config')
    def test_start_transcription_disabled(self, mock_config, client):
        """Test start when transcription is disabled."""
        mock_config.transcription_enabled = False

        response = client.post("/transcription/start/test123")

        assert response.status_code == 400
        assert "Transcription not enabled" in response.json()["detail"]

    @patch('routes.transcription.os.path.exists')
    @patch('routes.transcription.config')
    def test_start_transcription_audio_not_found(self, mock_config, mock_exists, client):
        """Test start when audio file doesn't exist."""
        mock_config.transcription_enabled = True
        mock_config.get_audio_path.return_value = "/tmp/test123.mp3"
        mock_exists.return_value = False

        response = client.post("/transcription/start/test123")

        assert response.status_code == 404
        assert "Audio file not found" in response.json()["detail"]

    @patch('routes.transcription.get_transcription_queue')
    @patch('routes.transcription.os.path.exists')
    @patch('routes.transcription.config')
    def test_start_transcription_success(self, mock_config, mock_exists, mock_get_queue, client):
        """Test successful transcription start."""
        mock_config.transcription_enabled = True
        mock_config.get_audio_path.return_value = "/tmp/test123.mp3"
        mock_exists.return_value = True

        mock_queue = Mock()
        mock_get_queue.return_value = mock_queue

        response = client.post("/transcription/start/test123")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["video_id"] == "test123"

        # Verify job was added to queue
        mock_queue.add_job.assert_called_once()
        job = mock_queue.add_job.call_args[0][0]
        assert job.video_id == "test123"
        assert job.audio_path == "/tmp/test123.mp3"

    @patch('routes.transcription.get_transcription_queue')
    @patch('routes.transcription.os.path.exists')
    @patch('routes.transcription.config')
    def test_start_transcription_error(self, mock_config, mock_exists, mock_get_queue, client):
        """Test start transcription with error."""
        mock_config.transcription_enabled = True
        mock_config.get_audio_path.return_value = "/tmp/test123.mp3"
        mock_exists.return_value = True
        mock_get_queue.side_effect = Exception("Queue error")

        response = client.post("/transcription/start/test123")

        assert response.status_code == 500
        assert "Queue error" in response.json()["detail"]


class TestGetSummary:
    """Tests for /transcription/summary/{video_id} endpoint."""

    @patch('routes.transcription.config')
    def test_get_summary_transcription_disabled(self, mock_config, client):
        """Test get summary when transcription is disabled."""
        mock_config.transcription_enabled = False

        response = client.get("/transcription/summary/test123")

        assert response.status_code == 400
        assert "Transcription not enabled" in response.json()["detail"]

    @patch('routes.transcription.get_transcription_queue')
    @patch('routes.transcription.config')
    def test_get_summary_job_not_found(self, mock_config, mock_get_queue, client):
        """Test get summary when job not found."""
        mock_config.transcription_enabled = True

        mock_queue = Mock()
        mock_queue.get_job_status.return_value = None
        mock_get_queue.return_value = mock_queue

        response = client.get("/transcription/summary/test123")

        assert response.status_code == 404
        assert "No transcription found" in response.json()["detail"]

    @patch('routes.transcription.get_transcription_queue')
    @patch('routes.transcription.config')
    def test_get_summary_job_pending(self, mock_config, mock_get_queue, client):
        """Test get summary when job is still pending."""
        mock_config.transcription_enabled = True

        mock_job = TranscriptionJob(video_id="test123", audio_path="/tmp/test.mp3")
        mock_job.status = JobStatus.TRANSCRIBING

        mock_queue = Mock()
        mock_queue.get_job_status.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        response = client.get("/transcription/summary/test123")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "transcribing"
        assert data["summary"] is None
        assert "not yet completed" in data["error"]

    @patch('routes.transcription.get_transcription_queue')
    @patch('routes.transcription.config')
    def test_get_summary_completed(self, mock_config, mock_get_queue, client):
        """Test get summary for completed job."""
        mock_config.transcription_enabled = True

        mock_job = TranscriptionJob(video_id="test123", audio_path="/tmp/test.mp3")
        mock_job.status = JobStatus.COMPLETED
        mock_job.summary = "This is the summary"
        mock_job.trilium_note_url = "http://trilium/note123"

        mock_queue = Mock()
        mock_queue.get_job_status.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        response = client.get("/transcription/summary/test123")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["summary"] == "This is the summary"
        assert data["trilium_note_url"] == "http://trilium/note123"

    @patch('routes.transcription.get_transcription_queue')
    @patch('routes.transcription.config')
    def test_get_summary_skipped(self, mock_config, mock_get_queue, client):
        """Test get summary for skipped job (deduplicated)."""
        mock_config.transcription_enabled = True

        mock_job = TranscriptionJob(video_id="test123", audio_path="/tmp/test.mp3")
        mock_job.status = JobStatus.SKIPPED
        mock_job.summary = "Existing summary"
        mock_job.trilium_note_url = "http://trilium/note123"

        mock_queue = Mock()
        mock_queue.get_job_status.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        response = client.get("/transcription/summary/test123")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "skipped"
        assert data["summary"] == "Existing summary"

    @patch('routes.transcription.get_transcription_queue')
    @patch('routes.transcription.config')
    def test_get_summary_error(self, mock_config, mock_get_queue, client):
        """Test get summary with error."""
        mock_config.transcription_enabled = True
        mock_get_queue.side_effect = Exception("Queue error")

        response = client.get("/transcription/summary/test123")

        assert response.status_code == 500
        assert "Queue error" in response.json()["detail"]
