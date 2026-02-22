"""Integration tests for queue type handling — uses real SQLite database.

Tests that summary items round-trip correctly through the database layer.
"""

import tempfile
from pathlib import Path


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

        init_database()

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

        init_database()

        add_to_queue("dQw4w9WgXcQ", "Rick Astley", "Channel", "thumb.jpg")

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

            yt = queue[0]
            assert yt.type == "youtube"
            assert yt.youtube_id == "dQw4w9WgXcQ"
            yt_dict = yt.to_dict()
            assert "week_year" not in yt_dict

            sm = queue[1]
            assert sm.type == "summary"
            assert sm.week_year == "2026-W09"
            sm_dict = sm.to_dict()
            assert sm_dict["week_year"] == "2026-W09"
            assert sm_dict["type"] == "summary"
        finally:
            Path(audio_path).unlink(missing_ok=True)
