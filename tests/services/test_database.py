"""Tests for database service."""

import os
import tempfile
import pytest
from services.database import (
    init_database,
    add_to_history,
    get_history,
    clear_history,
    add_to_queue,
    get_queue,
    get_next_in_queue,
    remove_from_queue,
    clear_queue,
    get_video_title_from_history,
    get_db_connection,
)


@pytest.fixture(autouse=True)
def db_path(monkeypatch):
    """Create temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name

    # Set environment variable BEFORE importing services
    monkeypatch.setenv("DATABASE_PATH", path)

    # Reload the database module to pick up new path
    import services.database
    import importlib

    importlib.reload(services.database)

    yield path

    # Cleanup
    if os.path.exists(path):
        try:
            os.unlink(path)
        except Exception:
            pass


class TestDatabaseInit:
    """Tests for database initialization."""

    def test_init_database_creates_tables(self, db_path):
        """Test that init_database creates the required tables."""
        init_database()

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Check play_history table
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='play_history'"
            )
            assert cursor.fetchone() is not None

            # Check queue table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='queue'")
            assert cursor.fetchone() is not None

    def test_init_database_idempotent(self, db_path):
        """Test that init_database can be called multiple times."""
        init_database()
        init_database()  # Should not raise


class TestPlayHistory:
    """Tests for play history functionality."""

    def test_add_to_history_new_video(self, db_path):
        """Test adding a new video to history."""
        init_database()

        video_id = "test123"
        title = "Test Video"

        history_id = add_to_history(video_id, title)

        assert history_id > 0

        # Verify in database
        history = get_history(limit=10)
        assert len(history) == 1
        assert history[0]["youtube_id"] == video_id
        assert history[0]["title"] == title
        assert history[0]["play_count"] == 1

    def test_add_to_history_duplicate_increments_count(self, db_path):
        """Test that playing the same video increments play_count."""
        init_database()

        video_id = "test123"
        title = "Test Video"

        # Add first time
        add_to_history(video_id, title)

        # Add second time
        add_to_history(video_id, title)

        # Verify play count increased
        history = get_history(limit=10)
        assert len(history) == 1
        assert history[0]["play_count"] == 2

    def test_add_to_history_updates_last_played(self, db_path):
        """Test that last_played_at is updated on replay."""
        init_database()

        video_id = "test123"
        title = "Test Video"

        # Add first time
        add_to_history(video_id, title)
        history1 = get_history(limit=1)
        first_played = history1[0]["last_played_at"]

        # Add second time
        add_to_history(video_id, title)
        history2 = get_history(limit=1)
        second_played = history2[0]["last_played_at"]

        # Last played should be updated
        assert second_played >= first_played

    def test_get_history_limit(self, db_path):
        """Test that get_history respects limit parameter."""
        init_database()

        # Add 15 videos
        for i in range(15):
            add_to_history(f"video{i}", f"Title {i}")

        # Get only 10
        history = get_history(limit=10)
        assert len(history) == 10

    def test_get_history_ordered_by_recent(self, db_path):
        """Test that get_history returns most recent first."""
        init_database()

        add_to_history("video1", "First")
        add_to_history("video2", "Second")
        add_to_history("video3", "Third")

        history = get_history(limit=10)

        # Most recent should be first
        assert history[0]["youtube_id"] == "video3"
        assert history[1]["youtube_id"] == "video2"
        assert history[2]["youtube_id"] == "video1"

    def test_clear_history(self, db_path):
        """Test clearing all history."""
        init_database()

        # Add some videos
        add_to_history("video1", "Title 1")
        add_to_history("video2", "Title 2")

        # Clear
        clear_history()

        # Verify empty
        history = get_history(limit=10)
        assert len(history) == 0

    def test_get_video_title_from_history(self, db_path):
        """Test retrieving video title from history."""
        init_database()

        video_id = "test123"
        title = "Test Video Title"

        add_to_history(video_id, title)

        # Retrieve title
        retrieved_title = get_video_title_from_history(video_id)
        assert retrieved_title == title

    def test_get_video_title_from_history_not_found(self, db_path):
        """Test retrieving title for non-existent video."""
        init_database()

        retrieved_title = get_video_title_from_history("nonexistent")
        assert retrieved_title is None


class TestQueue:
    """Tests for queue functionality."""

    def test_add_to_queue(self, db_path):
        """Test adding a video to the queue."""
        init_database()

        video_id = "test123"
        title = "Test Video"

        queue_id = add_to_queue(video_id, title)

        assert queue_id > 0

        # Verify in database
        queue = get_queue()
        assert len(queue) == 1
        assert queue[0]["youtube_id"] == video_id
        assert queue[0]["title"] == title
        assert queue[0]["position"] == 0  # Positions start at 0

    def test_add_to_queue_positions(self, db_path):
        """Test that queue items get sequential positions."""
        init_database()

        # Add multiple items
        add_to_queue("video1", "Title 1")
        add_to_queue("video2", "Title 2")
        add_to_queue("video3", "Title 3")

        queue = get_queue()

        assert len(queue) == 3
        assert queue[0]["position"] == 0  # Positions start at 0
        assert queue[1]["position"] == 1
        assert queue[2]["position"] == 2

    def test_get_next_in_queue(self, db_path):
        """Test getting the next item in queue."""
        init_database()

        add_to_queue("video1", "Title 1")
        add_to_queue("video2", "Title 2")

        next_item = get_next_in_queue()

        assert next_item is not None
        assert next_item["youtube_id"] == "video1"
        assert next_item["position"] == 0  # Positions start at 0

    def test_get_next_in_queue_empty(self, db_path):
        """Test getting next item when queue is empty."""
        init_database()

        next_item = get_next_in_queue()

        assert next_item is None

    def test_remove_from_queue(self, db_path):
        """Test removing an item from the queue."""
        init_database()

        queue_id = add_to_queue("video1", "Title 1")
        add_to_queue("video2", "Title 2")

        # Remove first item
        success = remove_from_queue(queue_id)

        assert success is True

        # Verify removed
        queue = get_queue()
        assert len(queue) == 1
        assert queue[0]["youtube_id"] == "video2"

    def test_remove_from_queue_reorders_positions(self, db_path):
        """Test that removing item reorders positions."""
        init_database()

        id1 = add_to_queue("video1", "Title 1")
        add_to_queue("video2", "Title 2")
        add_to_queue("video3", "Title 3")

        # Remove first item
        remove_from_queue(id1)

        queue = get_queue()

        # Positions should be 0, 1 (reordered after removal)
        assert queue[0]["position"] == 0
        assert queue[1]["position"] == 1

    def test_remove_from_queue_nonexistent(self, db_path):
        """Test removing non-existent item returns False."""
        init_database()

        success = remove_from_queue(99999)

        assert success is False

    def test_clear_queue(self, db_path):
        """Test clearing entire queue."""
        init_database()

        # Add items
        add_to_queue("video1", "Title 1")
        add_to_queue("video2", "Title 2")

        # Clear
        clear_queue()

        # Verify empty
        queue = get_queue()
        assert len(queue) == 0
