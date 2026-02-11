"""
Tests for summary items in the queue — type handling, playback flow, and serialization.

These tests verify that weekly summary items are correctly:
- Stored in the queue with type='summary' and week_year set
- Returned from the API with correct type and week_year fields
- Handled by /queue/next with proper type-specific response fields
- Distinguishable from YouTube items throughout the entire flow
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
        # Empty string is NOT None, so it should be preserved (not converted)
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
            _youtube_item(id=1, position=0),  # Current item (will be removed)
            _summary_item(id=2, position=1),  # Next item (summary)
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
            _summary_item(id=1, position=0),  # Current item (summary, will be removed)
            _youtube_item(id=2, position=1),  # Next item (youtube)
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


class TestDatabaseSummaryQueue:
    """Integration tests for add_summary_to_queue database function."""

    def test_summary_added_with_correct_type(self, db_path):
        """Summary added to queue should have type='summary'."""
        from services.database import (
            init_database,
            get_queue,
            save_weekly_summary,
            add_summary_to_queue,
        )
        import tempfile
        from pathlib import Path

        init_database()

        # Create a summary with an audio file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            audio_path = f.name

        try:
            save_weekly_summary(
                week_year="2026-W07",
                year=2026,
                week=7,
                title="Summary of week 2026-W07",
                trilium_note_id="test-note",
                audio_file_path=audio_path,
                duration_seconds=300,
            )

            queue_id = add_summary_to_queue("2026-W07")
            assert queue_id is not None

            queue = get_queue()
            summary_items = [item for item in queue if item.type == "summary"]
            assert len(summary_items) == 1

            item = summary_items[0]
            assert item.type == "summary"
            assert item.week_year == "2026-W07"
            assert item.youtube_id == ""
            assert item.title == "Summary of week 2026-W07"
        finally:
            Path(audio_path).unlink(missing_ok=True)

    def test_summary_to_dict_from_database(self, db_path):
        """Summary from database should serialize correctly with to_dict()."""
        from services.database import (
            init_database,
            get_queue,
            save_weekly_summary,
            add_summary_to_queue,
        )
        import tempfile
        from pathlib import Path

        init_database()

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            audio_path = f.name

        try:
            save_weekly_summary(
                week_year="2026-W08",
                year=2026,
                week=8,
                title="Summary of week 2026-W08",
                trilium_note_id="test-note-2",
                audio_file_path=audio_path,
                duration_seconds=200,
            )

            add_summary_to_queue("2026-W08")

            queue = get_queue()
            summary_items = [item for item in queue if item.type == "summary"]
            assert len(summary_items) == 1

            d = summary_items[0].to_dict()
            assert d["type"] == "summary"
            assert d["week_year"] == "2026-W08"
            assert d["youtube_id"] == ""
        finally:
            Path(audio_path).unlink(missing_ok=True)

    def test_mixed_queue_from_database(self, db_path):
        """Queue with both youtube and summary items should serialize correctly."""
        from services.database import (
            init_database,
            get_queue,
            add_to_queue,
            save_weekly_summary,
            add_summary_to_queue,
        )
        import tempfile
        from pathlib import Path

        init_database()

        # Add a YouTube item
        add_to_queue("dQw4w9WgXcQ", "Rick Astley", "Channel", "thumb.jpg")

        # Add a summary item
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio data")
            audio_path = f.name

        try:
            save_weekly_summary(
                week_year="2026-W09",
                year=2026,
                week=9,
                title="Summary of week 2026-W09",
                trilium_note_id="test-note-3",
                audio_file_path=audio_path,
                duration_seconds=180,
            )

            add_summary_to_queue("2026-W09")

            queue = get_queue()
            assert len(queue) == 2

            # First item: YouTube
            yt = queue[0]
            assert yt.type == "youtube"
            assert yt.youtube_id == "dQw4w9WgXcQ"
            yt_dict = yt.to_dict()
            assert "week_year" not in yt_dict

            # Second item: Summary
            sm = queue[1]
            assert sm.type == "summary"
            assert sm.week_year == "2026-W09"
            sm_dict = sm.to_dict()
            assert sm_dict["week_year"] == "2026-W09"
            assert sm_dict["type"] == "summary"
        finally:
            Path(audio_path).unlink(missing_ok=True)


class TestStreamEndpointValidation:
    """Tests for /stream endpoint — empty video_id validation."""

    def test_stream_rejects_empty_video_id(self):
        """POST /stream should return 400 for empty video_id."""
        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app)
        response = client.post(
            "/stream",
            json={"youtube_video_id": ""},
        )
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_stream_rejects_whitespace_only_video_id(self):
        """POST /stream should return 400 for whitespace-only video_id."""
        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app)
        response = client.post(
            "/stream",
            json={"youtube_video_id": "   "},
        )
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()
