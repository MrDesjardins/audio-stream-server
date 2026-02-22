"""Tests for database service."""

from services.database import (
    init_database,
    add_to_history,
    get_history,
    clear_history,
    add_to_queue,
    get_queue,
    get_next_in_queue,
    get_queue_hash,
    remove_from_queue,
    clear_queue,
    reorder_queue,
    get_video_title_from_history,
    get_db_connection,
    save_playback_position,
    get_playback_position,
    clear_playback_position,
)

# Note: The temp_db fixture from conftest.py is used automatically
# for all tests (autouse=True), so no need to define it here


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
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='queue'"
            )
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
        assert history[0].youtube_id == video_id
        assert history[0].title == title
        assert history[0].play_count == 1

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
        assert history[0].play_count == 2

    def test_add_to_history_updates_last_played(self, db_path):
        """Test that last_played_at is updated on replay."""
        init_database()

        video_id = "test123"
        title = "Test Video"

        # Add first time
        add_to_history(video_id, title)
        history1 = get_history(limit=1)
        first_played = history1[0].last_played_at

        # Add second time
        add_to_history(video_id, title)
        history2 = get_history(limit=1)
        second_played = history2[0].last_played_at

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
        assert history[0].youtube_id == "video3"
        assert history[1].youtube_id == "video2"
        assert history[2].youtube_id == "video1"

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
        assert queue[0].youtube_id == video_id
        assert queue[0].title == title
        assert queue[0].position == 0  # Positions start at 0

    def test_add_to_queue_positions(self, db_path):
        """Test that queue items get sequential positions."""
        init_database()

        # Add multiple items
        add_to_queue("video1", "Title 1")
        add_to_queue("video2", "Title 2")
        add_to_queue("video3", "Title 3")

        queue = get_queue()

        assert len(queue) == 3
        assert queue[0].position == 0  # Positions start at 0
        assert queue[1].position == 1
        assert queue[2].position == 2

    def test_get_next_in_queue(self, db_path):
        """Test getting the next item in queue."""
        init_database()

        add_to_queue("video1", "Title 1")
        add_to_queue("video2", "Title 2")

        next_item = get_next_in_queue()

        assert next_item is not None
        assert next_item.youtube_id == "video1"
        assert next_item.position == 0  # Positions start at 0

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
        assert queue[0].youtube_id == "video2"

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
        assert queue[0].position == 0
        assert queue[1].position == 1

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

    def test_reorder_queue(self, db_path):
        """Test reordering queue items."""
        init_database()

        # Add items
        id1 = add_to_queue("video1", "Title 1")
        id2 = add_to_queue("video2", "Title 2")
        id3 = add_to_queue("video3", "Title 3")
        id4 = add_to_queue("video4", "Title 4")

        # Original order: [id1, id2, id3, id4] with positions [0, 1, 2, 3]
        queue = get_queue()
        assert queue[0].youtube_id == "video1"
        assert queue[1].youtube_id == "video2"
        assert queue[2].youtube_id == "video3"
        assert queue[3].youtube_id == "video4"

        # Reorder to: [id3, id1, id4, id2]
        new_order = [id3, id1, id4, id2]
        success = reorder_queue(new_order)

        assert success is True

        # Verify new order
        queue = get_queue()
        assert len(queue) == 4
        assert queue[0].id == id3
        assert queue[0].youtube_id == "video3"
        assert queue[0].position == 1

        assert queue[1].id == id1
        assert queue[1].youtube_id == "video1"
        assert queue[1].position == 2

        assert queue[2].id == id4
        assert queue[2].youtube_id == "video4"
        assert queue[2].position == 3

        assert queue[3].id == id2
        assert queue[3].youtube_id == "video2"
        assert queue[3].position == 4

    def test_reorder_queue_empty(self, db_path):
        """Test reordering empty queue."""
        init_database()

        success = reorder_queue([])

        assert success is True

        queue = get_queue()
        assert len(queue) == 0

    def test_reorder_queue_single_item(self, db_path):
        """Test reordering queue with single item."""
        init_database()

        id1 = add_to_queue("video1", "Title 1")

        success = reorder_queue([id1])

        assert success is True

        queue = get_queue()
        assert len(queue) == 1
        assert queue[0].id == id1
        assert queue[0].position == 1

    def test_reorder_queue_reverse_order(self, db_path):
        """Test reversing queue order."""
        init_database()

        id1 = add_to_queue("video1", "Title 1")
        id2 = add_to_queue("video2", "Title 2")
        id3 = add_to_queue("video3", "Title 3")

        # Reverse order
        success = reorder_queue([id3, id2, id1])

        assert success is True

        queue = get_queue()
        assert queue[0].youtube_id == "video3"
        assert queue[1].youtube_id == "video2"
        assert queue[2].youtube_id == "video1"

    def test_reorder_queue_preserves_metadata(self, db_path):
        """Test that reordering preserves item metadata."""
        init_database()

        id1 = add_to_queue("video1", "Title 1", "Channel 1", "http://thumb1.jpg")
        id2 = add_to_queue("video2", "Title 2", "Channel 2", "http://thumb2.jpg")

        # Reorder
        reorder_queue([id2, id1])

        queue = get_queue()
        # After reordering, video2 is first but keeps its own metadata
        assert queue[0].youtube_id == "video2"
        assert queue[0].title == "Title 2"
        assert queue[0].channel == "Channel 2"
        assert queue[0].thumbnail_url == "http://thumb2.jpg"

        # video1 is second but keeps its own metadata
        assert queue[1].youtube_id == "video1"
        assert queue[1].title == "Title 1"
        assert queue[1].channel == "Channel 1"
        assert queue[1].thumbnail_url == "http://thumb1.jpg"


class TestPlaybackPositions:
    """Tests for playback position persistence."""

    def test_save_and_get_position(self, db_path):
        """Test saving and retrieving a playback position."""
        init_database()
        save_playback_position("abc123", 120.5, 3600.0)
        pos = get_playback_position("abc123")
        assert pos is not None
        assert pos.youtube_id == "abc123"
        assert pos.position_seconds == 120.5
        assert pos.duration_seconds == 3600.0

    def test_upsert_updates_existing(self, db_path):
        """Test that saving overwrites the previous position."""
        init_database()
        save_playback_position("abc123", 100.0)
        save_playback_position("abc123", 200.0, 3600.0)
        pos = get_playback_position("abc123")
        assert pos.position_seconds == 200.0
        assert pos.duration_seconds == 3600.0

    def test_get_nonexistent_returns_none(self, db_path):
        """Test that getting an unknown video ID returns None."""
        init_database()
        assert get_playback_position("nonexistent") is None

    def test_clear_position(self, db_path):
        """Test that clearing a position removes it."""
        init_database()
        save_playback_position("abc123", 100.0)
        clear_playback_position("abc123")
        assert get_playback_position("abc123") is None

    def test_save_without_duration(self, db_path):
        """Test saving a position without a duration."""
        init_database()
        save_playback_position("noDuration", 55.0)
        pos = get_playback_position("noDuration")
        assert pos is not None
        assert pos.position_seconds == 55.0
        assert pos.duration_seconds is None

    def test_to_dict(self, db_path):
        """Test PlaybackPosition.to_dict() serialization."""
        init_database()
        save_playback_position("abc123", 120.5, 3600.0)
        pos = get_playback_position("abc123")
        d = pos.to_dict()
        assert d["youtube_id"] == "abc123"
        assert d["position_seconds"] == 120.5
        assert d["duration_seconds"] == 3600.0
        assert "last_updated_at" in d


class TestGetQueueHash:
    """Tests for get_queue_hash() change-detection helper."""

    def test_empty_queue_returns_zero(self, db_path):
        """Empty queue produces hash of 0."""
        init_database()
        assert get_queue_hash() == 0

    def test_hash_changes_when_item_added(self, db_path):
        """Hash differs after adding an item."""
        init_database()
        h1 = get_queue_hash()
        add_to_queue("vid1", "Video 1")
        h2 = get_queue_hash()
        assert h1 != h2

    def test_hash_changes_when_item_removed(self, db_path):
        """Hash differs after removing an item."""
        init_database()
        qid = add_to_queue("vid1", "Video 1")
        h1 = get_queue_hash()
        remove_from_queue(qid)
        h2 = get_queue_hash()
        assert h1 != h2

    def test_hash_consistent_for_same_state(self, db_path):
        """Calling hash twice with no changes returns the same value."""
        init_database()
        add_to_queue("vid1", "Video 1")
        assert get_queue_hash() == get_queue_hash()

    def test_hash_returns_zero_after_clear(self, db_path):
        """Hash returns to 0 after the queue is cleared."""
        init_database()
        add_to_queue("vid1", "Video 1")
        assert get_queue_hash() != 0
        clear_queue()
        assert get_queue_hash() == 0

    def test_hash_differs_with_different_item_count(self, db_path):
        """Hash is different when the queue has different numbers of items."""
        init_database()
        add_to_queue("vid1", "Video 1")
        h1 = get_queue_hash()
        add_to_queue("vid2", "Video 2")
        h2 = get_queue_hash()
        assert h1 != h2
