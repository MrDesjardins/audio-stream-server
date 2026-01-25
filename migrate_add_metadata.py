#!/usr/bin/env python3
"""
Migration script to add channel and thumbnail_url columns to database.

This adds metadata columns to both play_history and queue tables.
"""
import sqlite3
import logging
import os
import shutil
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DATABASE_PATH", "./audio_history.db")


def backup_database():
    """Create a backup of the database before migration."""
    if not os.path.exists(DB_PATH):
        logger.info("No database file exists yet, skipping backup")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{DB_PATH}.backup_{timestamp}"
    shutil.copy2(DB_PATH, backup_path)
    logger.info(f"Database backed up to {backup_path}")
    return backup_path


def column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def migrate():
    """Add channel and thumbnail_url columns to tables."""
    backup_path = backup_database()

    if not os.path.exists(DB_PATH):
        logger.info("No database to migrate. New schema will be created on first run.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Migrate play_history table
        if not column_exists(cursor, "play_history", "channel"):
            logger.info("Adding 'channel' column to play_history table")
            cursor.execute("""
                ALTER TABLE play_history
                ADD COLUMN channel TEXT
            """)
        else:
            logger.info("Column 'channel' already exists in play_history")

        if not column_exists(cursor, "play_history", "thumbnail_url"):
            logger.info("Adding 'thumbnail_url' column to play_history table")
            cursor.execute("""
                ALTER TABLE play_history
                ADD COLUMN thumbnail_url TEXT
            """)
        else:
            logger.info("Column 'thumbnail_url' already exists in play_history")

        # Migrate queue table
        if not column_exists(cursor, "queue", "channel"):
            logger.info("Adding 'channel' column to queue table")
            cursor.execute("""
                ALTER TABLE queue
                ADD COLUMN channel TEXT
            """)
        else:
            logger.info("Column 'channel' already exists in queue")

        if not column_exists(cursor, "queue", "thumbnail_url"):
            logger.info("Adding 'thumbnail_url' column to queue table")
            cursor.execute("""
                ALTER TABLE queue
                ADD COLUMN thumbnail_url TEXT
            """)
        else:
            logger.info("Column 'thumbnail_url' already exists in queue")

        conn.commit()
        logger.info("Migration completed successfully!")

        # Verify
        cursor.execute("PRAGMA table_info(play_history)")
        logger.info(f"play_history columns: {[row[1] for row in cursor.fetchall()]}")

        cursor.execute("PRAGMA table_info(queue)")
        logger.info(f"queue columns: {[row[1] for row in cursor.fetchall()]}")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        conn.rollback()

        if backup_path:
            logger.info(f"Restoring from backup: {backup_path}")
            conn.close()
            shutil.copy2(backup_path, DB_PATH)
            logger.info("Database restored from backup")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
