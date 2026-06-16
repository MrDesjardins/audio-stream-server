"""Tests for queue routes."""

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from routes.queue import router
from services.models import QueueItem


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
    @patch("routes.queue.enqueue_audio_prefetch")
    @patch("routes.queue.add_to_queue")
    def test_add_to_queue_success(
        self, mock_add, mock_enqueue, mock_extract, mock_get_metadata, client
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
        mock_enqueue.assert_called_once_with("test123")

    @patch("routes.queue.get_video_metadata")
    @patch("routes.queue.extract_video_id")
    @patch("routes.queue.enqueue_audio_prefetch")
    @patch("routes.queue.add_to_queue")
    def test_add_to_queue_still_succeeds_if_prefetch_enqueue_fails(
        self, mock_add, mock_enqueue, mock_extract, mock_get_metadata, client
    ):
        """Prefetch failures should not block adding an item to the queue."""
        mock_extract.return_value = "test123"
        mock_get_metadata.return_value = {
            "title": "Test Video Title",
            "channel": "Test Channel",
            "thumbnail_url": "https://example.com/thumb.jpg",
        }
        mock_add.return_value = 1
        mock_enqueue.side_effect = Exception("prefetch unavailable")

        response = client.post("/queue/add", json={"youtube_video_id": "test123"})

        assert response.status_code == 200
        assert response.json()["status"] == "added"

    @patch("routes.queue.get_video_metadata")
    @patch("routes.queue.extract_video_id")
    @patch("routes.queue.enqueue_audio_prefetch")
    @patch("routes.queue.add_to_queue")
    def test_add_to_queue_with_url(
        self, mock_add, mock_enqueue, mock_extract, mock_get_metadata, client
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
        mock_enqueue.assert_called_once_with("extracted123")

    @patch("routes.queue.get_video_metadata")
    @patch("routes.queue.extract_video_id")
    @patch("routes.queue.enqueue_audio_prefetch")
    @patch("routes.queue.add_to_queue")
    def test_add_to_queue_no_title_uses_fallback(
        self, mock_add, mock_enqueue, mock_extract, mock_get_metadata, client
    ):
        """Test using fallback title when title fetch fails."""
        mock_extract.return_value = "test123"
        mock_get_metadata.return_value = None  # Metadata fetch failed
        mock_add.return_value = 1

        response = client.post("/queue/add", json={"youtube_video_id": "test123"})

        assert response.status_code == 200
        data = response.json()
        assert "YouTube Video test123" in data["title"]
        mock_enqueue.assert_called_once_with("test123")

    @patch("routes.queue.extract_video_id")
    @patch("routes.queue.enqueue_audio_prefetch")
    @patch("routes.queue.add_to_queue")
    def test_add_to_queue_database_error(
        self, mock_add, mock_enqueue, mock_extract, client
    ):
        """Test handling database error."""
        mock_extract.return_value = "test123"
        mock_add.side_effect = Exception("Database error")

        response = client.post("/queue/add", json={"youtube_video_id": "test123"})

        assert response.status_code == 500
        mock_enqueue.assert_not_called()


class TestGetQueueEndpoint:
    """Tests for /queue endpoint."""

    @patch("routes.queue.get_audio_prefetch_status")
    @patch("routes.queue.get_queue")
    def test_get_queue_success(self, mock_get_queue, mock_audio_status, client):
        """Test getting the queue."""
        mock_audio_status.side_effect = ["cached", "downloading"]
        mock_get_queue.return_value = [
            QueueItem(
                id=1,
                youtube_id="video1",
                title="Video 1",
                channel=None,
                thumbnail_url=None,
                position=1,
                created_at="2024-01-01T00:00:00",
                type="youtube",
                week_year=None,
            ),
            QueueItem(
                id=2,
                youtube_id="video2",
                title="Video 2",
                channel=None,
                thumbnail_url=None,
                position=2,
                created_at="2024-01-01T00:01:00",
                type="youtube",
                week_year=None,
            ),
        ]

        response = client.get("/queue")

        assert response.status_code == 200
        data = response.json()
        assert "queue" in data
        assert len(data["queue"]) == 2
        assert data["queue"][0]["youtube_id"] == "video1"
        assert data["queue"][1]["youtube_id"] == "video2"
        assert data["queue"][0]["audio_status"] == "cached"
        assert data["queue"][1]["audio_status"] == "downloading"

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

    @patch("routes.queue.get_next_in_queue_after_position")
    @patch("routes.queue.remove_from_queue")
    @patch("routes.queue.get_next_in_queue")
    def test_play_next_success(
        self, mock_get_next, mock_remove, mock_get_after, client
    ):
        """Test successfully playing next item."""
        mock_get_next.return_value = QueueItem(
            id=1,
            youtube_id="video1",
            title="Video 1",
            channel=None,
            thumbnail_url=None,
            position=1,
            created_at="2024-01-01T00:00:00",
            type="youtube",
            week_year=None,
        )
        mock_get_after.return_value = QueueItem(
            id=2,
            youtube_id="video2",
            title="Video 2",
            channel=None,
            thumbnail_url=None,
            position=2,
            created_at="2024-01-01T00:01:00",
            type="youtube",
            week_year=None,
        )
        mock_remove.return_value = True

        response = client.post("/queue/next")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "next"
        assert data["youtube_id"] == "video2"
        assert data["title"] == "Video 2"
        assert data["queue_id"] == 2

        mock_remove.assert_called_with(1)
        mock_get_after.assert_called_with(1)

    @patch("routes.queue.get_next_in_queue_after_position")
    @patch("routes.queue.remove_from_queue")
    @patch("routes.queue.get_queue_item_by_id")
    def test_play_next_removes_specified_queue_id(
        self, mock_get_by_id, mock_remove, mock_get_after, client
    ):
        """Test playing next removes the specified item, not always the first."""
        mock_get_by_id.return_value = QueueItem(
            id=3,
            youtube_id="video3",
            title="Video 3",
            channel=None,
            thumbnail_url=None,
            position=3,
            created_at="2024-01-01T00:02:00",
            type="youtube",
            week_year=None,
        )
        mock_get_after.return_value = QueueItem(
            id=4,
            youtube_id="video4",
            title="Video 4",
            channel=None,
            thumbnail_url=None,
            position=4,
            created_at="2024-01-01T00:03:00",
            type="youtube",
            week_year=None,
        )
        mock_remove.return_value = True

        response = client.post("/queue/next", json={"queue_id": 3})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "next"
        assert data["queue_id"] == 4
        mock_remove.assert_called_with(3)
        mock_get_after.assert_called_with(3)

    @patch("routes.queue.get_next_in_queue")
    def test_play_next_empty_queue(self, mock_get_next, client):
        """Test playing next when queue is empty."""
        mock_get_next.return_value = None

        response = client.post("/queue/next")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queue_empty"

    @patch("routes.queue.get_next_in_queue_after_position")
    @patch("routes.queue.remove_from_queue")
    @patch("routes.queue.get_next_in_queue")
    def test_play_next_last_item(
        self, mock_get_next, mock_remove, mock_get_after, client
    ):
        """Test playing next when on last item."""
        mock_get_next.return_value = QueueItem(
            id=1,
            youtube_id="video1",
            title="Video 1",
            channel=None,
            thumbnail_url=None,
            position=1,
            created_at="2024-01-01T00:00:00",
            type="youtube",
            week_year=None,
        )
        mock_get_after.return_value = None
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


class TestPrefetchEndpoint:
    """Tests for /queue/prefetch endpoint."""

    @patch("routes.queue.enqueue_audio_prefetch")
    def test_prefetch_uses_shared_worker(self, mock_enqueue, client):
        """Prefetch endpoint queues work through the shared prefetcher."""
        mock_enqueue.return_value = "queued"

        response = client.post("/queue/prefetch/video123")

        assert response.status_code == 200
        assert response.json() == {"status": "queued", "video_id": "video123"}
        mock_enqueue.assert_called_once_with("video123")

    @patch("routes.queue.enqueue_audio_prefetch")
    def test_prefetch_returns_cached_status(self, mock_enqueue, client):
        """Prefetch endpoint returns normalized prefetch statuses."""
        mock_enqueue.return_value = "cached"

        response = client.post("/queue/prefetch/video123")

        assert response.status_code == 200
        assert response.json()["status"] == "cached"


class TestQueueAudioStatusHash:
    """Tests for queue audio readiness hash."""

    @patch("routes.queue.get_audio_prefetch_status")
    @patch("routes.queue.get_queue")
    def test_hash_changes_when_audio_status_changes(
        self, mock_get_queue, mock_audio_status
    ):
        """Audio readiness changes should produce a different status hash."""
        from routes.queue import get_queue_audio_status_hash

        mock_get_queue.return_value = [
            QueueItem(
                id=1,
                youtube_id="video1",
                title="Video 1",
                channel=None,
                thumbnail_url=None,
                position=1,
                created_at="2024-01-01T00:00:00",
                type="youtube",
                week_year=None,
            )
        ]
        mock_audio_status.return_value = "queued"
        queued_hash = get_queue_audio_status_hash()
        mock_audio_status.return_value = "cached"
        cached_hash = get_queue_audio_status_hash()

        assert queued_hash != cached_hash

    @patch("routes.queue.get_audio_prefetch_status")
    @patch("routes.queue.get_queue")
    def test_hash_ignores_summary_items(self, mock_get_queue, mock_audio_status):
        """Summary items do not need audio prefetch status."""
        from routes.queue import get_queue_audio_status_hash

        mock_get_queue.return_value = [
            QueueItem(
                id=2,
                youtube_id="",
                title="Summary",
                channel=None,
                thumbnail_url=None,
                position=1,
                created_at="2024-01-01T00:00:00",
                type="summary",
                week_year="2026-W01",
            )
        ]

        assert get_queue_audio_status_hash() == 0
        mock_audio_status.assert_not_called()


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
    @patch("routes.queue.enqueue_audio_prefetch")
    @patch("services.book_suggestions.get_video_suggestions")
    @patch("routes.queue.config")
    @pytest.mark.asyncio
    async def test_suggestions_success(
        self,
        mock_config,
        mock_get_suggestions,
        mock_enqueue,
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
        assert mock_enqueue.call_count == 2

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
    @patch("routes.queue.enqueue_audio_prefetch")
    @patch("services.book_suggestions.get_video_suggestions")
    @patch("routes.queue.config")
    @pytest.mark.asyncio
    async def test_suggestions_partial_failure(
        self,
        mock_config,
        mock_get_suggestions,
        mock_enqueue,
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
        assert mock_enqueue.call_count == 2

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


class TestReorderQueueEndpoint:
    """Tests for POST /queue/reorder endpoint."""

    @patch("routes.queue.reorder_queue")
    def test_reorder_queue_success(self, mock_reorder, client):
        """Test successfully reordering queue."""
        mock_reorder.return_value = True

        queue_ids = [3, 1, 2, 4]
        response = client.post("/queue/reorder", json={"queue_item_ids": queue_ids})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "reordered"
        assert data["count"] == 4

        # Verify reorder was called with correct IDs
        mock_reorder.assert_called_once_with(queue_ids)

    @patch("routes.queue.reorder_queue")
    def test_reorder_queue_empty_list(self, mock_reorder, client):
        """Test reordering with empty list."""
        mock_reorder.return_value = True

        response = client.post("/queue/reorder", json={"queue_item_ids": []})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "reordered"
        assert data["count"] == 0

    @patch("routes.queue.reorder_queue")
    def test_reorder_queue_single_item(self, mock_reorder, client):
        """Test reordering with single item."""
        mock_reorder.return_value = True

        response = client.post("/queue/reorder", json={"queue_item_ids": [1]})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "reordered"
        assert data["count"] == 1

    @patch("routes.queue.reorder_queue")
    def test_reorder_queue_failure(self, mock_reorder, client):
        """Test handling reorder failure."""
        mock_reorder.return_value = False

        response = client.post("/queue/reorder", json={"queue_item_ids": [1, 2, 3]})

        assert response.status_code == 500
        assert "Failed to reorder queue" in response.json()["detail"]

    @patch("routes.queue.reorder_queue")
    def test_reorder_queue_database_error(self, mock_reorder, client):
        """Test handling database error during reorder."""
        mock_reorder.side_effect = Exception("Database error")

        response = client.post("/queue/reorder", json={"queue_item_ids": [1, 2, 3]})

        assert response.status_code == 500

    def test_reorder_queue_invalid_payload(self, client):
        """Test reorder with invalid payload."""
        # Missing queue_item_ids field
        response = client.post("/queue/reorder", json={})

        assert response.status_code == 422  # Validation error

    def test_reorder_queue_invalid_types(self, client):
        """Test reorder with invalid data types."""
        # String instead of list
        response = client.post("/queue/reorder", json={"queue_item_ids": "not a list"})

        assert response.status_code == 422  # Validation error
