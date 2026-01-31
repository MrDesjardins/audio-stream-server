"""Tests for queue routes."""

from unittest.mock import patch
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

    @patch("routes.queue.get_video_metadata")
    @patch("routes.queue.extract_video_id")
    @patch("routes.queue.add_to_queue")
    def test_add_to_queue_success(
        self, mock_add, mock_extract, mock_get_metadata, client
    ):
        """Test successfully adding video to queue."""
        mock_extract.return_value = "test123"
        mock_get_metadata.return_value = {
            "title": "Test Video Title",
            "channel": "Test Channel",
            "thumbnail_url": "https://example.com/thumb.jpg",
        }
        mock_add.return_value = 1

        response = client.post("/queue/add", json={"youtube_video_id": "test123"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "added"
        assert data["queue_id"] == 1
        assert data["youtube_id"] == "test123"
        assert data["title"] == "Test Video Title"

    @patch("routes.queue.get_video_metadata")
    @patch("routes.queue.extract_video_id")
    @patch("routes.queue.add_to_queue")
    def test_add_to_queue_with_url(
        self, mock_add, mock_extract, mock_get_metadata, client
    ):
        """Test adding video with URL instead of ID."""
        mock_extract.return_value = "extracted123"
        mock_get_metadata.return_value = {
            "title": "Video Title",
            "channel": "Test Channel",
            "thumbnail_url": "https://example.com/thumb.jpg",
        }
        mock_add.return_value = 2

        response = client.post(
            "/queue/add",
            json={"youtube_video_id": "https://www.youtube.com/watch?v=extracted123"},
        )

        assert response.status_code == 200
        # Verify ID was extracted
        mock_extract.assert_called_with("https://www.youtube.com/watch?v=extracted123")

    @patch("routes.queue.get_video_metadata")
    @patch("routes.queue.extract_video_id")
    @patch("routes.queue.add_to_queue")
    def test_add_to_queue_no_title_uses_fallback(
        self, mock_add, mock_extract, mock_get_metadata, client
    ):
        """Test using fallback title when title fetch fails."""
        mock_extract.return_value = "test123"
        mock_get_metadata.return_value = None  # Metadata fetch failed
        mock_add.return_value = 1

        response = client.post("/queue/add", json={"youtube_video_id": "test123"})

        assert response.status_code == 200
        data = response.json()
        assert "YouTube Video test123" in data["title"]

    @patch("routes.queue.extract_video_id")
    @patch("routes.queue.add_to_queue")
    def test_add_to_queue_database_error(self, mock_add, mock_extract, client):
        """Test handling database error."""
        mock_extract.return_value = "test123"
        mock_add.side_effect = Exception("Database error")

        response = client.post("/queue/add", json={"youtube_video_id": "test123"})

        assert response.status_code == 500


class TestGetQueueEndpoint:
    """Tests for /queue endpoint."""

    @patch("routes.queue.get_queue")
    def test_get_queue_success(self, mock_get_queue, client):
        """Test getting the queue."""
        mock_get_queue.return_value = [
            {
                "id": 1,
                "youtube_id": "video1",
                "title": "Video 1",
                "position": 1,
                "created_at": "2024-01-01T00:00:00",
            },
            {
                "id": 2,
                "youtube_id": "video2",
                "title": "Video 2",
                "position": 2,
                "created_at": "2024-01-01T00:01:00",
            },
        ]

        response = client.get("/queue")

        assert response.status_code == 200
        data = response.json()
        assert "queue" in data
        assert len(data["queue"]) == 2
        assert data["queue"][0]["youtube_id"] == "video1"
        assert data["queue"][1]["youtube_id"] == "video2"

    @patch("routes.queue.get_queue")
    def test_get_queue_empty(self, mock_get_queue, client):
        """Test getting empty queue."""
        mock_get_queue.return_value = []

        response = client.get("/queue")

        assert response.status_code == 200
        data = response.json()
        assert data["queue"] == []

    @patch("routes.queue.get_queue")
    def test_get_queue_error(self, mock_get_queue, client):
        """Test handling error getting queue."""
        mock_get_queue.side_effect = Exception("Database error")

        response = client.get("/queue")

        assert response.status_code == 500


class TestRemoveFromQueueEndpoint:
    """Tests for DELETE /queue/{queue_id} endpoint."""

    @patch("routes.queue.remove_from_queue")
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

    @patch("routes.queue.remove_from_queue")
    def test_remove_from_queue_not_found(self, mock_remove, client):
        """Test removing non-existent item."""
        mock_remove.return_value = False

        response = client.delete("/queue/999")

        assert response.status_code == 404
        assert "Queue item not found" in response.json()["detail"]

    @patch("routes.queue.remove_from_queue")
    def test_remove_from_queue_error(self, mock_remove, client):
        """Test handling error during removal."""
        mock_remove.side_effect = Exception("Database error")

        response = client.delete("/queue/1")

        assert response.status_code == 500


class TestPlayNextEndpoint:
    """Tests for /queue/next endpoint."""

    @patch("routes.queue.get_next_in_queue")
    @patch("routes.queue.remove_from_queue")
    def test_play_next_success(self, mock_remove, mock_get_next, client):
        """Test successfully playing next item."""
        # First call returns current item, second returns next
        mock_get_next.side_effect = [
            {"id": 1, "youtube_id": "video1", "title": "Video 1", "position": 1},
            {"id": 2, "youtube_id": "video2", "title": "Video 2", "position": 2},
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

    @patch("routes.queue.get_next_in_queue")
    def test_play_next_empty_queue(self, mock_get_next, client):
        """Test playing next when queue is empty."""
        mock_get_next.return_value = None

        response = client.post("/queue/next")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queue_empty"

    @patch("routes.queue.get_next_in_queue")
    @patch("routes.queue.remove_from_queue")
    def test_play_next_last_item(self, mock_remove, mock_get_next, client):
        """Test playing next when on last item."""
        # First call returns current item, second returns None (no next)
        mock_get_next.side_effect = [
            {"id": 1, "youtube_id": "video1", "title": "Video 1", "position": 1},
            None,  # No next item
        ]
        mock_remove.return_value = True

        response = client.post("/queue/next")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queue_empty"

    @patch("routes.queue.get_next_in_queue")
    def test_play_next_error(self, mock_get_next, client):
        """Test handling error in play next."""
        mock_get_next.side_effect = Exception("Database error")

        response = client.post("/queue/next")

        assert response.status_code == 500


class TestClearQueueEndpoint:
    """Tests for /queue/clear endpoint."""

    @patch("routes.queue.clear_queue")
    def test_clear_queue_success(self, mock_clear, client):
        """Test successfully clearing queue."""
        response = client.post("/queue/clear")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cleared"

        # Verify clear was called
        mock_clear.assert_called_once()

    @patch("routes.queue.clear_queue")
    def test_clear_queue_error(self, mock_clear, client):
        """Test handling error clearing queue."""
        mock_clear.side_effect = Exception("Database error")

        response = client.post("/queue/clear")

        assert response.status_code == 500


class TestSuggestionsEndpoint:
    """Tests for /queue/suggestions endpoint."""

    @patch("routes.queue.config")
    def test_suggestions_disabled(self, mock_config, client):
        """Test when suggestions feature is disabled."""
        mock_config.book_suggestions_enabled = False

        response = client.post("/queue/suggestions")

        assert response.status_code == 400
        assert "disabled" in response.json()["detail"]

    @patch("routes.queue.get_video_metadata")
    @patch("routes.queue.add_to_queue")
    @patch("services.book_suggestions.get_video_suggestions")
    @patch("routes.queue.config")
    @pytest.mark.asyncio
    async def test_suggestions_success(
        self,
        mock_config,
        mock_get_suggestions,
        mock_add_to_queue,
        mock_get_metadata,
        client,
    ):
        """Test successful suggestion generation and queuing."""
        mock_config.book_suggestions_enabled = True

        # Mock suggestions
        mock_get_suggestions.return_value = [
            {
                "title": "Atomic Habits",
                "author": "James Clear",
                "video_id": "dQw4w9WgXcQ",
                "youtube_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
            },
            {
                "title": "Deep Work",
                "author": "Cal Newport",
                "video_id": "jNQXAC9IVRw",
                "youtube_url": "https://youtube.com/watch?v=jNQXAC9IVRw",
            },
        ]

        # Mock metadata fetching
        mock_get_metadata.side_effect = [
            {
                "title": "Atomic Habits Full Audiobook",
                "channel": "Audiobooks Channel",
                "thumbnail_url": "https://example.com/thumb1.jpg",
            },
            {
                "title": "Deep Work Audiobook",
                "channel": "Books Audio",
                "thumbnail_url": "https://example.com/thumb2.jpg",
            },
        ]

        # Mock queue addition
        mock_add_to_queue.side_effect = [1, 2]

        response = client.post("/queue/suggestions")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert len(data["added"]) == 2
        assert data["added"][0]["video_id"] == "dQw4w9WgXcQ"
        assert data["added"][0]["title"] == "Atomic Habits Full Audiobook"

    @patch("services.book_suggestions.get_video_suggestions")
    @patch("routes.queue.config")
    @pytest.mark.asyncio
    async def test_suggestions_no_results(
        self, mock_config, mock_get_suggestions, client
    ):
        """Test when no suggestions are generated."""
        mock_config.book_suggestions_enabled = True
        mock_get_suggestions.return_value = []

        response = client.post("/queue/suggestions")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "no_suggestions"
        assert len(data.get("added", [])) == 0

    @patch("routes.queue.get_video_metadata")
    @patch("routes.queue.add_to_queue")
    @patch("services.book_suggestions.get_video_suggestions")
    @patch("routes.queue.config")
    @pytest.mark.asyncio
    async def test_suggestions_partial_failure(
        self,
        mock_config,
        mock_get_suggestions,
        mock_add_to_queue,
        mock_get_metadata,
        client,
    ):
        """Test when some suggestions fail to add."""
        mock_config.book_suggestions_enabled = True

        mock_get_suggestions.return_value = [
            {
                "title": "Book 1",
                "author": "Author 1",
                "video_id": "dQw4w9WgXcQ",
                "youtube_url": "url1",
            },
            {
                "title": "Book 2",
                "author": "Author 2",
                "video_id": "jNQXAC9IVRw",
                "youtube_url": "url2",
            },
        ]

        # First succeeds, second fails
        mock_get_metadata.side_effect = [
            {"title": "Book 1", "channel": "Channel", "thumbnail_url": "url"},
            None,  # Metadata fetch fails
        ]

        mock_add_to_queue.side_effect = [1, 2]

        response = client.post("/queue/suggestions")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert (
            len(data["added"]) == 2
        )  # Both should be added (second uses fallback title)

    @patch("services.book_suggestions.get_video_suggestions")
    @patch("routes.queue.config")
    @pytest.mark.asyncio
    async def test_suggestions_error(self, mock_config, mock_get_suggestions, client):
        """Test error handling in suggestions endpoint."""
        mock_config.book_suggestions_enabled = True
        mock_get_suggestions.side_effect = Exception("API error")

        response = client.post("/queue/suggestions")

        assert response.status_code == 500
        assert "Failed to generate suggestions" in response.json()["detail"]
