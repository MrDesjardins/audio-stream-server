"""Tests for queue routes."""
from unittest.mock import patch, Mock
import pytest
from fastapi.testclient import TestClient
from routes.queue import router


@pytest.fixture
def client():
    """FastAPI test client for queue router."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    return TestClient(app)


class TestAddToQueueEndpoint:
    """Tests for /queue/add endpoint."""

    @patch('routes.queue.get_video_title')
    @patch('routes.queue.extract_video_id')
    @patch('routes.queue.add_to_queue')
    def test_add_to_queue_success(self, mock_add, mock_extract, mock_get_title, client):
        """Test successfully adding video to queue."""
        mock_extract.return_value = "test123"
        mock_get_title.return_value = "Test Video Title"
        mock_add.return_value = 1

        response = client.post("/queue/add", json={"youtube_video_id": "test123"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "added"
        assert data["queue_id"] == 1
        assert data["youtube_id"] == "test123"
        assert data["title"] == "Test Video Title"

    @patch('routes.queue.get_video_title')
    @patch('routes.queue.extract_video_id')
    @patch('routes.queue.add_to_queue')
    def test_add_to_queue_with_url(self, mock_add, mock_extract, mock_get_title, client):
        """Test adding video with URL instead of ID."""
        mock_extract.return_value = "extracted123"
        mock_get_title.return_value = "Video Title"
        mock_add.return_value = 2

        response = client.post("/queue/add", json={
            "youtube_video_id": "https://www.youtube.com/watch?v=extracted123"
        })

        assert response.status_code == 200
        # Verify ID was extracted
        mock_extract.assert_called_with("https://www.youtube.com/watch?v=extracted123")

    @patch('routes.queue.get_video_title')
    @patch('routes.queue.extract_video_id')
    @patch('routes.queue.add_to_queue')
    def test_add_to_queue_no_title_uses_fallback(
        self, mock_add, mock_extract, mock_get_title, client
    ):
        """Test using fallback title when title fetch fails."""
        mock_extract.return_value = "test123"
        mock_get_title.return_value = None  # Title fetch failed
        mock_add.return_value = 1

        response = client.post("/queue/add", json={"youtube_video_id": "test123"})

        assert response.status_code == 200
        data = response.json()
        assert "YouTube Video test123" in data["title"]

    @patch('routes.queue.extract_video_id')
    @patch('routes.queue.add_to_queue')
    def test_add_to_queue_database_error(self, mock_add, mock_extract, client):
        """Test handling database error."""
        mock_extract.return_value = "test123"
        mock_add.side_effect = Exception("Database error")

        response = client.post("/queue/add", json={"youtube_video_id": "test123"})

        assert response.status_code == 500


class TestGetQueueEndpoint:
    """Tests for /queue endpoint."""

    @patch('routes.queue.get_queue')
    def test_get_queue_success(self, mock_get_queue, client):
        """Test getting the queue."""
        mock_get_queue.return_value = [
            {
                "id": 1,
                "youtube_id": "video1",
                "title": "Video 1",
                "position": 1,
                "created_at": "2024-01-01T00:00:00"
            },
            {
                "id": 2,
                "youtube_id": "video2",
                "title": "Video 2",
                "position": 2,
                "created_at": "2024-01-01T00:01:00"
            }
        ]

        response = client.get("/queue")

        assert response.status_code == 200
        data = response.json()
        assert "queue" in data
        assert len(data["queue"]) == 2
        assert data["queue"][0]["youtube_id"] == "video1"
        assert data["queue"][1]["youtube_id"] == "video2"

    @patch('routes.queue.get_queue')
    def test_get_queue_empty(self, mock_get_queue, client):
        """Test getting empty queue."""
        mock_get_queue.return_value = []

        response = client.get("/queue")

        assert response.status_code == 200
        data = response.json()
        assert data["queue"] == []

    @patch('routes.queue.get_queue')
    def test_get_queue_error(self, mock_get_queue, client):
        """Test handling error getting queue."""
        mock_get_queue.side_effect = Exception("Database error")

        response = client.get("/queue")

        assert response.status_code == 500


class TestRemoveFromQueueEndpoint:
    """Tests for DELETE /queue/{queue_id} endpoint."""

    @patch('routes.queue.remove_from_queue')
    def test_remove_from_queue_success(self, mock_remove, client):
        """Test successfully removing item from queue."""
        mock_remove.return_value = True

        response = client.delete("/queue/1")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "removed"
        assert data["queue_id"] == 1

        # Verify correct ID was passed
        mock_remove.assert_called_with(1)

    @patch('routes.queue.remove_from_queue')
    def test_remove_from_queue_not_found(self, mock_remove, client):
        """Test removing non-existent item."""
        mock_remove.return_value = False

        response = client.delete("/queue/999")

        assert response.status_code == 404
        assert "Queue item not found" in response.json()["detail"]

    @patch('routes.queue.remove_from_queue')
    def test_remove_from_queue_error(self, mock_remove, client):
        """Test handling error during removal."""
        mock_remove.side_effect = Exception("Database error")

        response = client.delete("/queue/1")

        assert response.status_code == 500


class TestPlayNextEndpoint:
    """Tests for /queue/next endpoint."""

    @patch('routes.queue.get_next_in_queue')
    @patch('routes.queue.remove_from_queue')
    def test_play_next_success(self, mock_remove, mock_get_next, client):
        """Test successfully playing next item."""
        # First call returns current item, second returns next
        mock_get_next.side_effect = [
            {
                "id": 1,
                "youtube_id": "video1",
                "title": "Video 1",
                "position": 1
            },
            {
                "id": 2,
                "youtube_id": "video2",
                "title": "Video 2",
                "position": 2
            }
        ]
        mock_remove.return_value = True

        response = client.post("/queue/next")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "next"
        assert data["youtube_id"] == "video2"
        assert data["title"] == "Video 2"
        assert data["queue_id"] == 2

        # Verify current was removed
        mock_remove.assert_called_with(1)

    @patch('routes.queue.get_next_in_queue')
    def test_play_next_empty_queue(self, mock_get_next, client):
        """Test playing next when queue is empty."""
        mock_get_next.return_value = None

        response = client.post("/queue/next")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queue_empty"

    @patch('routes.queue.get_next_in_queue')
    @patch('routes.queue.remove_from_queue')
    def test_play_next_last_item(self, mock_remove, mock_get_next, client):
        """Test playing next when on last item."""
        # First call returns current item, second returns None (no next)
        mock_get_next.side_effect = [
            {
                "id": 1,
                "youtube_id": "video1",
                "title": "Video 1",
                "position": 1
            },
            None  # No next item
        ]
        mock_remove.return_value = True

        response = client.post("/queue/next")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queue_empty"

    @patch('routes.queue.get_next_in_queue')
    def test_play_next_error(self, mock_get_next, client):
        """Test handling error in play next."""
        mock_get_next.side_effect = Exception("Database error")

        response = client.post("/queue/next")

        assert response.status_code == 500


class TestClearQueueEndpoint:
    """Tests for /queue/clear endpoint."""

    @patch('routes.queue.clear_queue')
    def test_clear_queue_success(self, mock_clear, client):
        """Test successfully clearing queue."""
        response = client.post("/queue/clear")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cleared"

        # Verify clear was called
        mock_clear.assert_called_once()

    @patch('routes.queue.clear_queue')
    def test_clear_queue_error(self, mock_clear, client):
        """Test handling error clearing queue."""
        mock_clear.side_effect = Exception("Database error")

        response = client.post("/queue/clear")

        assert response.status_code == 500
