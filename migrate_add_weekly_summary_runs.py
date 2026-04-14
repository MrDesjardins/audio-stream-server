#!/usr/bin/env python3
"""Database migration to add weekly summary retry state."""

import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("DATABASE_PATH", "./audio_history.db")


def migrate_database() -> bool:
    """Create weekly_summary_runs table if it does not exist."""
    db_path = Path(DB_PATH)
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return False

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS weekly_summary_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_year TEXT NOT NULL UNIQUE,
                target_date TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_retry_at TEXT,
                last_error TEXT,
                missing_video_ids TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_weekly_summary_runs_due
            ON weekly_summary_runs(status, next_retry_at)
        """)
        conn.commit()
        conn.close()
        print("Weekly summary run migration completed successfully")
        return True
    except Exception as e:
        print(f"Weekly summary run migration failed: {e}")
        return False


if __name__ == "__main__":
    raise SystemExit(0 if migrate_database() else 1)
