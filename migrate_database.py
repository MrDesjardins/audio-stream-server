#!/usr/bin/env python3
"""
Database migration script for audio-stream-server.
Migrates from old schema (without play_count) to new schema (with play_count).
"""

import sqlite3
import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DATABASE_PATH", "./audio_history.db")


def check_schema_version(conn):
    """Check if the database has the new schema with play_count."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(play_history)")
    columns = [col[1] for col in cursor.fetchall()]

    has_play_count = 'play_count' in columns
    has_last_played_at = 'last_played_at' in columns

    return has_play_count, has_last_played_at


def migrate_database():
    """Migrate the database from old schema to new schema."""
    if not os.path.exists(DB_PATH):
        logger.info("No existing database found. Skipping migration.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        has_play_count, has_last_played_at = check_schema_version(conn)

        if has_play_count and has_last_played_at:
            logger.info("Database already has the new schema. No migration needed.")
            conn.close()
            return

        logger.info("Starting database migration...")

        # Create backup
        backup_path = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        logger.info(f"Creating backup at {backup_path}")
        backup_conn = sqlite3.connect(backup_path)
        conn.backup(backup_conn)
        backup_conn.close()

        cursor = conn.cursor()

        # Create new table with updated schema
        logger.info("Creating new table with updated schema...")
        cursor.execute("""
            CREATE TABLE play_history_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                youtube_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                play_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_played_at TEXT NOT NULL
            )
        """)

        # Migrate data: group by youtube_id, count plays, keep most recent title
        logger.info("Migrating data from old table to new table...")
        cursor.execute("""
            INSERT INTO play_history_new (youtube_id, title, play_count, created_at, last_played_at)
            SELECT
                youtube_id,
                (SELECT title FROM play_history p2
                 WHERE p2.youtube_id = p1.youtube_id
                 ORDER BY p2.created_at DESC
                 LIMIT 1) as title,
                COUNT(*) as play_count,
                MIN(created_at) as created_at,
                MAX(created_at) as last_played_at
            FROM play_history p1
            GROUP BY youtube_id
            ORDER BY MAX(created_at) DESC
        """)

        # Get count of migrated records
        cursor.execute("SELECT COUNT(*) FROM play_history_new")
        new_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM play_history")
        old_count = cursor.fetchone()[0]

        logger.info(f"Migrated {old_count} records into {new_count} unique videos")

        # Drop old table and rename new table
        logger.info("Replacing old table with new table...")
        cursor.execute("DROP TABLE play_history")
        cursor.execute("ALTER TABLE play_history_new RENAME TO play_history")

        # Recreate indexes
        logger.info("Creating indexes...")
        cursor.execute("""
            CREATE INDEX idx_youtube_id ON play_history(youtube_id)
        """)
        cursor.execute("""
            CREATE INDEX idx_last_played_at ON play_history(last_played_at DESC)
        """)

        conn.commit()
        logger.info("✓ Migration completed successfully!")
        logger.info(f"✓ Backup saved at {backup_path}")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate_database()
