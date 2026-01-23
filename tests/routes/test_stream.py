"""Tests for stream routes."""
import asyncio
import queue as queue_module
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import pytest
from fastapi.testclient import TestClient
from routes.stream import router, init_stream_globals
from services.broadcast import StreamBroadcaster


@pytest.fixture
def client():
    """FastAPI test client for stream router."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    # Initialize globals
    import threading
    process_lock = threading.Lock()
    broadcaster = StreamBroadcaster()
    init_stream_globals(process_lock, broadcaster)

    return TestClient(app)


class TestStreamEndpoint:
    """Tests for /stream endpoint."""

    @patch('routes.stream.get_video_title')
    @patch('routes.stream.add_to_history')
    @patch('routes.stream.extract_video_id')
    @patch('routes.stream.start_youtube_stream')
    @patch('routes.stream.config')
    def test_stream_endpoint_success(
        self, mock_config, mock_start_stream, mock_extract, mock_add_history, mock_get_title, client
    ):
        """Test successful stream start."""
        # Mock config
        mock_config.transcription_enabled = False

        # Mock functions
        mock_extract.return_value = "test123"
        mock_get_title.return_value = "Test Video"
        mock_add_history.return_value = 1
        mock_start_stream.return_value = Mock()

        response = client.post("/stream", json={"youtube_video_id": "test123"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stream started"
        assert data["youtube_video_id"] == "test123"
        assert data["title"] == "Test Video"

    @patch('routes.stream.get_video_title')
    @patch('routes.stream.extract_video_id')
    @patch('routes.stream.config')
    def test_stream_endpoint_with_url(self, mock_config, mock_extract, mock_get_title, client):
        """Test streaming with YouTube URL."""
        mock_config.transcription_enabled = False
        mock_extract.return_value = "extractedID"
        mock_get_title.return_value = "Video Title"

        response = client.post("/stream", json={
            "youtube_video_id": "https://www.youtube.com/watch?v=extractedID"
        })

        assert response.status_code == 200
        # Verify video ID was extracted
        mock_extract.assert_called_with("https://www.youtube.com/watch?v=extractedID")

    @patch('routes.stream.get_video_title')
    @patch('routes.stream.add_to_history')
    @patch('routes.stream.extract_video_id')
    @patch('routes.stream.get_transcription_queue')
    @patch('routes.stream.config')
    def test_stream_endpoint_with_transcription(
        self, mock_config, mock_queue, mock_extract, mock_add_history, mock_get_title, client
    ):
        """Test streaming with transcription enabled."""
        mock_config.transcription_enabled = True
        mock_config.get_audio_path = lambda vid: f"/tmp/{vid}.mp3"

        mock_extract.return_value = "test123"
        mock_get_title.return_value = "Test Video"

        # Mock transcription queue
        mock_queue_obj = Mock()
        mock_queue_obj.add_job = Mock()
        mock_queue.return_value = mock_queue_obj

        response = client.post("/stream", json={
            "youtube_video_id": "test123",
            "skip_transcription": False
        })

        assert response.status_code == 200
        # Verify transcription job was queued
        mock_queue_obj.add_job.assert_called_once()

    @patch('routes.stream.get_video_title')
    @patch('routes.stream.extract_video_id')
    @patch('routes.stream.config')
    def test_stream_endpoint_skip_transcription(
        self, mock_config, mock_extract, mock_get_title, client
    ):
        """Test streaming with skip_transcription=True."""
        mock_config.transcription_enabled = True

        mock_extract.return_value = "test123"
        mock_get_title.return_value = "Test Video"

        response = client.post("/stream", json={
            "youtube_video_id": "test123",
            "skip_transcription": True
        })

        assert response.status_code == 200


class TestStopEndpoint:
    """Tests for /stop endpoint."""

    @patch('routes.stream.current_process', None)
    def test_stop_no_stream_running(self, client):
        """Test stop when no stream is running."""
        response = client.post("/stop")

        assert response.status_code == 400
        assert "No stream running" in response.json()["detail"]

    @patch('routes.stream.current_process')
    def test_stop_success(self, mock_process, client):
        """Test successfully stopping stream."""
        # Set up mock process
        import routes.stream
        mock_proc = Mock()
        routes.stream.current_process = mock_proc

        response = client.post("/stop")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stream stopped"

        # Verify process was terminated
        mock_proc.terminate.assert_called_once()


class TestStatusEndpoint:
    """Tests for /status endpoint."""

    @patch('routes.stream.current_process', None)
    def test_status_idle(self, client):
        """Test status when idle."""
        response = client.get("/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "idle"

    @patch('routes.stream.current_process')
    def test_status_streaming(self, mock_process, client):
        """Test status when streaming."""
        import routes.stream
        routes.stream.current_process = Mock()

        response = client.get("/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "streaming"


class TestMyStreamEndpoint:
    """Tests for /mystream endpoint."""

    @pytest.mark.asyncio
    @patch('routes.stream.broadcaster')
    async def test_mystream_no_active_stream(self, mock_broadcaster, client):
        """Test accessing stream when none is active."""
        mock_broadcaster.is_active.return_value = False

        response = client.get("/mystream")

        assert response.status_code == 400
        assert "No active stream" in response.json()["detail"]

    @patch('routes.stream.broadcaster')
    def test_mystream_active_stream(self, mock_broadcaster, client):
        """Test streaming when active."""
        # Mock active broadcaster
        mock_broadcaster.is_active.return_value = True

        # Create a mock queue that returns some data then EOF
        mock_queue = Mock()
        mock_queue.get = Mock(side_effect=[b"chunk1", b"chunk2", None])
        mock_broadcaster.subscribe.return_value = mock_queue

        response = client.get("/mystream")

        # Should get streaming response
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"


class TestHistoryEndpoints:
    """Tests for history endpoints."""

    @patch('routes.stream.get_history')
    def test_get_history_success(self, mock_get_history, client):
        """Test getting play history."""
        mock_get_history.return_value = [
            {
                "id": 1,
                "youtube_id": "test123",
                "title": "Test Video",
                "play_count": 2,
                "created_at": "2024-01-01T00:00:00",
                "last_played_at": "2024-01-02T00:00:00"
            }
        ]

        response = client.get("/history")

        assert response.status_code == 200
        data = response.json()
        assert "history" in data
        assert len(data["history"]) == 1
        assert data["history"][0]["youtube_id"] == "test123"

    @patch('routes.stream.get_history')
    def test_get_history_with_limit(self, mock_get_history, client):
        """Test getting history with custom limit."""
        mock_get_history.return_value = []

        response = client.get("/history?limit=5")

        assert response.status_code == 200
        # Verify limit was passed
        mock_get_history.assert_called_with(limit=5)

    @patch('routes.stream.clear_history')
    def test_clear_history_success(self, mock_clear, client):
        """Test clearing history."""
        response = client.post("/history/clear")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cleared"

        # Verify clear was called
        mock_clear.assert_called_once()
