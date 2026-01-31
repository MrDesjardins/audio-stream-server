#!/usr/bin/env python3
"""
Database migration to add weekly_summaries table and extend queue table.

This migration:
1. Creates weekly_summaries table to track audio summaries
2. Adds 'type' column to queue table (defaults to 'youtube')
3. Adds 'week_year' column to queue table for summary references
"""

import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

DB_PATH = "./audio_history.db"


def backup_database():
    """Create a backup of the database before migration."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{DB_PATH}.backup_{timestamp}"
    shutil.copy2(DB_PATH, backup_path)
    print(f"✓ Created backup: {backup_path}")
    return backup_path


def check_if_migration_needed(conn):
    """Check if migration has already been applied."""
    cursor = conn.cursor()

    # Check if weekly_summaries table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='weekly_summaries'
    """)
    has_summaries_table = cursor.fetchone() is not None

    # Check if queue table has 'type' column
    cursor.execute("PRAGMA table_info(queue)")
    columns = {row[1] for row in cursor.fetchall()}
    has_type_column = "type" in columns

    if has_summaries_table and has_type_column:
        print("✓ Migration already applied, skipping")
        return False

    return True


def migrate_database():
    """Run the migration."""
    print("Starting weekly summary migration...")

    if not Path(DB_PATH).exists():
        print(f"✗ Database not found at {DB_PATH}")
        return False

    # Create backup
    backup_path = backup_database()

    try:
        conn = sqlite3.connect(DB_PATH)

        # Check if migration needed
        if not check_if_migration_needed(conn):
            conn.close()
            return True

        cursor = conn.cursor()

        # Create weekly_summaries table
        print("Creating weekly_summaries table...")
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

        # Check if queue table needs migration
        cursor.execute("PRAGMA table_info(queue)")
        columns = {row[1] for row in cursor.fetchall()}

        if "type" not in columns:
            print("Adding 'type' column to queue table...")
            cursor.execute("ALTER TABLE queue ADD COLUMN type TEXT DEFAULT 'youtube'")

        if "week_year" not in columns:
            print("Adding 'week_year' column to queue table...")
            cursor.execute("ALTER TABLE queue ADD COLUMN week_year TEXT")

        # Update existing queue items to have type='youtube'
        cursor.execute("UPDATE queue SET type='youtube' WHERE type IS NULL")

        conn.commit()
        print("✓ Migration completed successfully")

        # Verify tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"✓ Tables in database: {', '.join(tables)}")

        conn.close()
        return True

    except Exception as e:
        print(f"✗ Migration failed: {e}")
        print(f"  Restoring from backup: {backup_path}")
        shutil.copy2(backup_path, DB_PATH)
        return False


if __name__ == "__main__":
    success = migrate_database()
    exit(0 if success else 1)
