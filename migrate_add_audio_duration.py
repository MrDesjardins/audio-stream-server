"""
Database migration: Add audio_duration_seconds column to llm_usage_stats.

This enables accurate cost tracking for per-minute pricing models like Whisper and Voxtral.
"""

import os
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime


def migrate_add_audio_duration():
    """Add audio_duration_seconds column to llm_usage_stats table."""
    db_path_str = os.getenv("DATABASE_PATH", "./audio_history.db")
    db_path = Path(db_path_str).expanduser().resolve()

    if not db_path.exists():
        print(f"❌ Database not found at {db_path}. Nothing to migrate.")
        return

    # Create backup
    backup_path = db_path.with_suffix(
        f"{db_path.suffix}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    shutil.copy2(db_path, backup_path)
    print(f"✅ Created backup: {backup_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(llm_usage_stats)")
        columns = [row[1] for row in cursor.fetchall()]

        if "audio_duration_seconds" in columns:
            print(
                "✅ Column 'audio_duration_seconds' already exists. No migration needed."
            )
            return

        # Add the new column (nullable, since existing records won't have this data)
        print("Adding 'audio_duration_seconds' column...")
        cursor.execute(
            """
            ALTER TABLE llm_usage_stats
            ADD COLUMN audio_duration_seconds REAL
        """
        )

        conn.commit()
        print("✅ Successfully added 'audio_duration_seconds' column")

        # Show updated schema
        cursor.execute("PRAGMA table_info(llm_usage_stats)")
        print("\n📋 Updated table schema:")
        for row in cursor.fetchall():
            print(f"  - {row[1]} ({row[2]})")

    except Exception as e:
        conn.rollback()
        print(f"❌ Migration failed: {e}")
        print(f"Database restored from backup: {backup_path}")
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    print("🔄 Starting database migration: Add audio_duration_seconds column")
    migrate_add_audio_duration()
    print("\n✅ Migration completed successfully!")
