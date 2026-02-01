"""
Migration script to add type and week_year columns to queue table.

This migration adds support for queuing weekly summaries alongside YouTube videos.
"""

import os
import sqlite3
import sys
from pathlib import Path

# Add parent directory to path for imports

sys.path.insert(0, str(Path(__file__).parent))

from services.path_utils import expand_path


def migrate_queue_table() -> None:
    """Add type and week_year columns to queue table if they don't exist."""
    db_path_str = os.getenv("DATABASE_PATH", "./audio_history.db")
    db_path = expand_path(db_path_str)

    print(f"Migrating database: {db_path}")

    # Check if database exists
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    # Create backup
    backup_path = db_path.with_suffix(f"{db_path.suffix}.backup-queue-columns")
    print(f"Creating backup: {backup_path}")
    import shutil

    shutil.copy2(db_path, backup_path)

    # Connect to database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(queue)")
        columns = [row[1] for row in cursor.fetchall()]

        changes_made = False

        # Add type column if it doesn't exist
        if "type" not in columns:
            print("Adding 'type' column to queue table...")
            cursor.execute("""
                ALTER TABLE queue ADD COLUMN type TEXT DEFAULT 'youtube'
            """)
            # Update existing rows to have 'youtube' type
            cursor.execute("""
                UPDATE queue SET type = 'youtube' WHERE type IS NULL
            """)
            changes_made = True
            print("✓ Added 'type' column")
        else:
            print("✓ 'type' column already exists")

        # Add week_year column if it doesn't exist
        if "week_year" not in columns:
            print("Adding 'week_year' column to queue table...")
            cursor.execute("""
                ALTER TABLE queue ADD COLUMN week_year TEXT
            """)
            changes_made = True
            print("✓ Added 'week_year' column")
        else:
            print("✓ 'week_year' column already exists")

        if changes_made:
            conn.commit()
            print("\n✅ Migration completed successfully!")
            print(f"Backup saved at: {backup_path}")
        else:
            print("\n✅ No migration needed - columns already exist")
            # Remove unnecessary backup
            backup_path.unlink()

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        conn.rollback()
        print(f"Database has been rolled back. Backup available at: {backup_path}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    migrate_queue_table()
