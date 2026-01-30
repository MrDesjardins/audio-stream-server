import sqlite3
import logging
import threading
from datetime import datetime, timezone
from typing import List, Optional, Dict
from contextlib import contextmanager
from queue import Queue, Empty
import os

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DATABASE_PATH", "./audio_history.db")


class ConnectionPool:
    """Thread-safe SQLite connection pool."""

    def __init__(self, db_path: str, max_connections: int = 5):
        self.db_path = db_path
        self.pool: Queue[sqlite3.Connection] = Queue(maxsize=max_connections)
        self.lock = threading.Lock()

        # Pre-create connections
        for _ in range(max_connections):
            conn = self._create_connection()
            self.pool.put(conn)

    def _create_connection(self):
        """Create a new database connection."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def get_connection(self):
        """Get a connection from the pool."""
        try:
            conn = self.pool.get(timeout=5)
            temp_conn = False
        except Empty:
            # Pool exhausted, create temporary connection
            logger.warning("Connection pool exhausted, creating temp connection")
            conn = self._create_connection()
            temp_conn = True

        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            if temp_conn:
                conn.close()
            else:
                self.pool.put(conn)

    def close_all(self):
        """Close all connections in pool."""
        while not self.pool.empty():
            try:
                conn = self.pool.get_nowait()
                conn.close()
            except Empty:
                break


# Global pool instance
_db_pool = None


def get_db_pool():
    """Get database connection pool singleton."""
    global _db_pool
    if _db_pool is None:
        _db_pool = ConnectionPool(DB_PATH)
    return _db_pool


@contextmanager
def get_db_connection():
    """Context manager for database connections (updated to use pool)."""
    pool = get_db_pool()
    with pool.get_connection() as conn:
        yield conn


def init_database():
    """Initialize the database with the required schema."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Play history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS play_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                youtube_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                channel TEXT,
                thumbnail_url TEXT,
                play_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_played_at TEXT NOT NULL
            )
        """)

        # Create index on youtube_id for faster lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_youtube_id
            ON play_history(youtube_id)
        """)

        # Create index on last_played_at for faster sorting
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_last_played_at
            ON play_history(last_played_at DESC)
        """)

        # Queue table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                youtube_id TEXT NOT NULL,
                title TEXT NOT NULL,
                channel TEXT,
                thumbnail_url TEXT,
                position INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                type TEXT DEFAULT 'youtube',
                week_year TEXT
            )
        """)

        # Weekly summaries table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS weekly_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_year TEXT NOT NULL UNIQUE,
                year INTEGER NOT NULL,
                week INTEGER NOT NULL,
                title TEXT NOT NULL,
                trilium_note_id TEXT NOT NULL,
                audio_file_path TEXT,
                duration_seconds INTEGER,
                created_at TEXT NOT NULL,
                audio_generated_at TEXT
            )
        """)

        # Create index on position for faster ordering
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_queue_position
            ON queue(position ASC)
        """)

        logger.info(f"Database initialized at {DB_PATH}")


def add_to_history(
    youtube_id: str, title: str, channel: Optional[str] = None, thumbnail_url: Optional[str] = None
) -> int:
    """
    Add a video to play history or increment play count if it already exists.

    Args:
        youtube_id: YouTube video ID
        title: Video title
        channel: Channel name (optional)
        thumbnail_url: Thumbnail URL (optional)

    Returns:
        The ID of the record
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Use UPSERT: Insert if new, update if exists
        cursor.execute(
            """
            INSERT INTO play_history (youtube_id, title, channel, thumbnail_url, play_count, created_at, last_played_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(youtube_id) DO UPDATE SET
                title = excluded.title,
                channel = excluded.channel,
                thumbnail_url = excluded.thumbnail_url,
                play_count = play_count + 1,
                last_played_at = excluded.last_played_at
        """,
            (youtube_id, title, channel, thumbnail_url, timestamp, timestamp),
        )

        # Get the record ID
        cursor.execute(
            "SELECT id, play_count FROM play_history WHERE youtube_id = ?", (youtube_id,)
        )
        row = cursor.fetchone()
        record_id = row["id"]
        play_count = row["play_count"]

        logger.info(f"Updated history: {title} ({youtube_id}) - Play count: {play_count}")
        return record_id


def get_history(limit: int = 10) -> List[Dict]:
    """
    Get play history, most recently played first.

    Args:
        limit: Maximum number of records to return

    Returns:
        List of history records as dictionaries
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, youtube_id, title, channel, thumbnail_url, play_count, created_at, last_played_at
            FROM play_history
            ORDER BY last_played_at DESC
            LIMIT ?
        """,
            (limit,),
        )

        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_video_title_from_history(youtube_id: str) -> Optional[str]:
    """
    Get the title for a video from history.

    Args:
        youtube_id: YouTube video ID

    Returns:
        The title if found, None otherwise
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT title
            FROM play_history
            WHERE youtube_id = ?
            LIMIT 1
        """,
            (youtube_id,),
        )

        row = cursor.fetchone()
        return row["title"] if row else None


def clear_history():
    """Delete all history records."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM play_history")
        logger.info("History cleared")


# Queue management functions


def add_to_queue(
    youtube_id: str, title: str, channel: Optional[str] = None, thumbnail_url: Optional[str] = None
) -> int:
    """
    Add a video to the end of the queue.

    Args:
        youtube_id: YouTube video ID
        title: Video title
        channel: Channel name (optional)
        thumbnail_url: Thumbnail URL (optional)

    Returns:
        The ID of the inserted queue item
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Get the max position
        cursor.execute("SELECT MAX(position) FROM queue")
        max_pos = cursor.fetchone()[0]
        next_position = (max_pos + 1) if max_pos is not None else 0

        cursor.execute(
            """
            INSERT INTO queue (youtube_id, title, channel, thumbnail_url, position, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (youtube_id, title, channel, thumbnail_url, next_position, timestamp),
        )

        record_id = cursor.lastrowid
        logger.info(f"Added to queue (position {next_position}): {title} ({youtube_id})")
        return record_id


def get_queue() -> List[Dict]:
    """
    Get the current queue, ordered by position.

    Returns:
        List of queue items as dictionaries
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, youtube_id, title, channel, thumbnail_url, position, created_at
            FROM queue
            ORDER BY position ASC
        """)

        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_next_in_queue() -> Optional[Dict]:
    """
    Get the first item in the queue (lowest position).

    Returns:
        Queue item dictionary or None if queue is empty
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, youtube_id, title, channel, thumbnail_url, position, created_at
            FROM queue
            ORDER BY position ASC
            LIMIT 1
        """)

        row = cursor.fetchone()
        return dict(row) if row else None


def remove_from_queue(queue_id: int) -> bool:
    """
    Remove a specific item from the queue and reorder remaining items.

    Args:
        queue_id: The queue item ID to remove

    Returns:
        True if item was removed, False if not found
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Get the position of the item to remove
        cursor.execute("SELECT position FROM queue WHERE id = ?", (queue_id,))
        row = cursor.fetchone()

        if not row:
            return False

        removed_position = row["position"]

        # Delete the item
        cursor.execute("DELETE FROM queue WHERE id = ?", (queue_id,))

        # Reorder remaining items (decrement positions greater than removed)
        cursor.execute(
            """
            UPDATE queue
            SET position = position - 1
            WHERE position > ?
        """,
            (removed_position,),
        )

        logger.info(f"Removed queue item {queue_id} and reordered queue")
        return True


def clear_queue():
    """Delete all queue items."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM queue")
        logger.info("Queue cleared")


# Weekly summary functions


def save_weekly_summary(
    week_year: str,
    year: int,
    week: int,
    title: str,
    trilium_note_id: str,
    audio_file_path: Optional[str] = None,
    duration_seconds: Optional[int] = None,
) -> int:
    """
    Save a weekly summary to the database.

    Args:
        week_year: Week identifier (e.g., "2026-W05")
        year: Year number
        week: Week number
        title: Summary title
        trilium_note_id: Trilium note ID
        audio_file_path: Path to audio file (optional)
        duration_seconds: Audio duration in seconds (optional)

    Returns:
        The ID of the inserted/updated record
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    audio_timestamp = timestamp if audio_file_path else None

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Use UPSERT: Insert if new, update if exists
        cursor.execute(
            """
            INSERT INTO weekly_summaries (
                week_year, year, week, title, trilium_note_id,
                audio_file_path, duration_seconds, created_at, audio_generated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(week_year) DO UPDATE SET
                title = excluded.title,
                trilium_note_id = excluded.trilium_note_id,
                audio_file_path = excluded.audio_file_path,
                duration_seconds = excluded.duration_seconds,
                audio_generated_at = excluded.audio_generated_at
        """,
            (
                week_year,
                year,
                week,
                title,
                trilium_note_id,
                audio_file_path,
                duration_seconds,
                timestamp,
                audio_timestamp,
            ),
        )

        # Get the record ID
        cursor.execute("SELECT id FROM weekly_summaries WHERE week_year = ?", (week_year,))
        row = cursor.fetchone()
        record_id = row["id"]

        logger.info(f"Saved weekly summary: {week_year} - {title}")
        return record_id


def get_recent_summaries(limit: int = 10) -> List[Dict]:
    """
    Get recent weekly summaries, most recent first.

    Args:
        limit: Maximum number of records to return

    Returns:
        List of summary records as dictionaries
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, week_year, year, week, title, trilium_note_id,
                   audio_file_path, duration_seconds, created_at, audio_generated_at
            FROM weekly_summaries
            ORDER BY year DESC, week DESC
            LIMIT ?
        """,
            (limit,),
        )

        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_summary_by_week_year(week_year: str) -> Optional[Dict]:
    """
    Get a specific weekly summary by week_year.

    Args:
        week_year: Week identifier (e.g., "2026-W05")

    Returns:
        Summary record dictionary or None if not found
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, week_year, year, week, title, trilium_note_id,
                   audio_file_path, duration_seconds, created_at, audio_generated_at
            FROM weekly_summaries
            WHERE week_year = ?
            LIMIT 1
        """,
            (week_year,),
        )

        row = cursor.fetchone()
        return dict(row) if row else None


def add_summary_to_queue(week_year: str) -> int:
    """
    Add a weekly summary to the playback queue.

    Args:
        week_year: Week identifier (e.g., "2026-W05")

    Returns:
        The ID of the inserted queue item

    Raises:
        ValueError: If summary not found or has no audio file
    """
    # Get summary details
    summary = get_summary_by_week_year(week_year)
    if not summary:
        raise ValueError(f"Summary not found: {week_year}")

    if not summary.get("audio_file_path"):
        raise ValueError(f"Summary has no audio file: {week_year}")

    timestamp = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Get the max position
        cursor.execute("SELECT MAX(position) FROM queue")
        max_pos = cursor.fetchone()[0]
        next_position = (max_pos + 1) if max_pos is not None else 0

        cursor.execute(
            """
            INSERT INTO queue (youtube_id, title, position, created_at, type, week_year)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            ("", summary["title"], next_position, timestamp, "summary", week_year),
        )

        record_id = cursor.lastrowid
        logger.info(f"Added summary to queue (position {next_position}): {summary['title']}")
        return record_id
