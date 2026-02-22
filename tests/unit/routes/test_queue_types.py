"""Unit tests for queue type handling — summary vs youtube items.

All database and external calls are mocked; only in-process logic is tested.
"""

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from routes.queue import router
from services.models import QueueItem


def _youtube_item(
    id: int = 1,
    youtube_id: str = "dQw4w9WgXcQ",
    title: str = "YouTube Video",
    position: int = 0,
) -> QueueItem:
    """Helper to create a YouTube QueueItem."""
    return QueueItem(
        id=id,
        youtube_id=youtube_id,
        title=title,
        channel="Test Channel",
        thumbnail_url="https://example.com/thumb.jpg",
        position=position,
        created_at="2026-01-01T00:00:00",
        type="youtube",
        week_year=None,
    )


def _summary_item(
    id: int = 10,
    week_year: str = "2026-W07",
    title: str = "Summary of week 2026-W07",
    position: int = 0,
) -> QueueItem:
    """Helper to create a summary QueueItem."""
    return QueueItem(
        id=id,
        youtube_id="",
        title=title,
        channel=None,
        thumbnail_url=None,
        position=position,
        created_at="2026-01-01T00:00:00",
        type="summary",
        week_year=week_year,
    )


@pytest.fixture
def client():
    """FastAPI test client for queue router."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestQueueItemModel:
    """Tests for QueueItem dataclass — type handling and serialization."""

    def test_youtube_item_to_dict_has_type_youtube(self):
        """YouTube items should have type='youtube' in dict."""
        item = _youtube_item()
        d = item.to_dict()
        assert d["type"] == "youtube"
        assert "week_year" not in d

    def test_summary_item_to_dict_has_type_summary(self):
        """Summary items should have type='summary' in dict."""
        item = _summary_item()
        d = item.to_dict()
        assert d["type"] == "summary"
        assert d["week_year"] == "2026-W07"

    def test_summary_item_to_dict_includes_week_year_even_if_none(self):
        """Summary items should include week_year even if it's None."""
        item = _summary_item(week_year=None)
        item.type = "summary"
        d = item.to_dict()
        assert "week_year" in d
        assert d["week_year"] is None

    def test_youtube_item_to_dict_excludes_week_year(self):
        """YouTube items should NOT include week_year in dict."""
        item = _youtube_item()
        d = item.to_dict()
        assert "week_year" not in d

    def test_from_db_row_preserves_summary_type(self):
        """from_db_row should preserve type='summary' from database."""
        row = {
            "id": 1,
            "youtube_id": "",
            "title": "Summary",
            "channel": None,
            "thumbnail_url": None,
            "position": 0,
            "created_at": "2026-01-01",
            "type": "summary",
            "week_year": "2026-W07",
        }
        item = QueueItem.from_db_row(row)
        assert item.type == "summary"
        assert item.week_year == "2026-W07"

    def test_from_db_row_defaults_none_type_to_youtube(self):
        """from_db_row should default None type to 'youtube'."""
        row = {
            "id": 1,
            "youtube_id": "abc123",
            "title": "Video",
            "channel": None,
            "thumbnail_url": None,
            "position": 0,
            "created_at": "2026-01-01",
            "type": None,
            "week_year": None,
        }
        item = QueueItem.from_db_row(row)
        assert item.type == "youtube"

    def test_from_db_row_preserves_empty_string_type(self):
        """from_db_row should NOT convert empty string to 'youtube'.

        Empty string is a valid (albeit unusual) value that should be preserved,
        not silently converted. This prevents 'summary' from being lost.
        """
        row = {
            "id": 1,
            "youtube_id": "abc123",
            "title": "Video",
            "channel": None,
            "thumbnail_url": None,
            "position": 0,
            "created_at": "2026-01-01",
            "type": "",
            "week_year": None,
        }
        item = QueueItem.from_db_row(row)
        assert item.type == ""

    def test_summary_to_dict_roundtrip(self):
        """Summary item should survive to_dict() roundtrip with all fields."""
        item = _summary_item(id=42, week_year="2026-W03", title="Week 3 Summary")
        d = item.to_dict()

        assert d["id"] == 42
        assert d["type"] == "summary"
        assert d["week_year"] == "2026-W03"
        assert d["title"] == "Week 3 Summary"
        assert d["youtube_id"] == ""


class TestQueueNextWithSummary:
    """Tests for /queue/next endpoint with summary items."""

    @patch("routes.queue.get_next_in_queue")
    @patch("routes.queue.remove_from_queue")
    def test_next_returns_summary_fields(self, mock_remove, mock_get_next, client):
        """When next item is a summary, response should have week_year, not youtube_id."""
        mock_get_next.side_effect = [
            _youtube_item(id=1, position=0),
            _summary_item(id=2, position=1),
        ]
        mock_remove.return_value = True

        response = client.post("/queue/next")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "next"
        assert data["type"] == "summary"
        assert data["week_year"] == "2026-W07"
        assert "youtube_id" not in data

    @patch("routes.queue.get_next_in_queue")
    @patch("routes.queue.remove_from_queue")
    def test_next_returns_youtube_fields(self, mock_remove, mock_get_next, client):
        """When next item is youtube, response should have youtube_id, not week_year."""
        mock_get_next.side_effect = [
            _summary_item(id=1, position=0),
            _youtube_item(id=2, position=1),
        ]
        mock_remove.return_value = True

        response = client.post("/queue/next")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "next"
        assert data["type"] == "youtube"
        assert data["youtube_id"] == "dQw4w9WgXcQ"
        assert "week_year" not in data

    @patch("routes.queue.get_next_in_queue")
    @patch("routes.queue.remove_from_queue")
    def test_next_summary_after_summary(self, mock_remove, mock_get_next, client):
        """When both current and next are summaries, should work correctly."""
        mock_get_next.side_effect = [
            _summary_item(id=1, week_year="2026-W06", position=0),
            _summary_item(id=2, week_year="2026-W07", position=1),
        ]
        mock_remove.return_value = True

        response = client.post("/queue/next")

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "summary"
        assert data["week_year"] == "2026-W07"
        assert data["queue_id"] == 2


class TestGetQueueWithSummary:
    """Tests for GET /queue with mixed youtube and summary items."""

    @patch("routes.queue.get_queue")
    def test_queue_returns_summary_with_correct_fields(self, mock_get_queue, client):
        """Summary items in queue should have type and week_year."""
        mock_get_queue.return_value = [
            _summary_item(id=1, week_year="2026-W07"),
        ]

        response = client.get("/queue")

        assert response.status_code == 200
        data = response.json()
        assert len(data["queue"]) == 1
        item = data["queue"][0]
        assert item["type"] == "summary"
        assert item["week_year"] == "2026-W07"
        assert item["youtube_id"] == ""

    @patch("routes.queue.get_queue")
    def test_queue_mixed_items_preserve_types(self, mock_get_queue, client):
        """Mixed queue should preserve correct types for each item."""
        mock_get_queue.return_value = [
            _youtube_item(id=1, position=0),
            _summary_item(id=2, position=1),
            _youtube_item(id=3, youtube_id="abc123", position=2),
        ]

        response = client.get("/queue")

        assert response.status_code == 200
        queue = response.json()["queue"]
        assert len(queue) == 3

        assert queue[0]["type"] == "youtube"
        assert "week_year" not in queue[0]

        assert queue[1]["type"] == "summary"
        assert queue[1]["week_year"] == "2026-W07"

        assert queue[2]["type"] == "youtube"
        assert "week_year" not in queue[2]
