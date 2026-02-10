#!/usr/bin/env python3
"""
Diagnostic script to check if the queue table has the required columns.
Run this to verify the database schema is up to date.
"""

import sqlite3
import os
import sys
from pathlib import Path


def check_queue_schema():
    """Check if queue table has type and week_year columns."""
    db_path = os.getenv("DATABASE_PATH", "./audio_history.db")

    # Expand path
    db_path = Path(db_path).expanduser().resolve()

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        print(f"   Current directory: {os.getcwd()}")
        print(f"   Looking for: {db_path}")
        return False

    print(f"✅ Database found: {db_path}")
    print()

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Get queue table schema
    cursor.execute("PRAGMA table_info(queue)")
    columns = cursor.fetchall()

    print("Queue table schema:")
    print("-" * 60)
    for col in columns:
        col_id, name, col_type, not_null, default, pk = col
        print(f"  {name:20s} {col_type:15s} ", end="")
        if not_null:
            print("NOT NULL ", end="")
        if default is not None:
            print(f"DEFAULT {default} ", end="")
        if pk:
            print("PRIMARY KEY ", end="")
        print()
    print("-" * 60)
    print()

    # Check for required columns
    column_names = [col[1] for col in columns]

    has_type = "type" in column_names
    has_week_year = "week_year" in column_names

    if has_type:
        print("✅ 'type' column exists")
    else:
        print("❌ 'type' column is MISSING")

    if has_week_year:
        print("✅ 'week_year' column exists")
    else:
        print("❌ 'week_year' column is MISSING")

    print()

    if not has_type or not has_week_year:
        print("⚠️  MIGRATION REQUIRED!")
        print()
        print("The queue table is missing required columns for weekly summaries.")
        print("Please run the migration:")
        print()
        print("    uv run python migrate_add_queue_columns.py")
        print()
        conn.close()
        return False

    # Check if there are any summary items in the queue
    cursor.execute("SELECT COUNT(*) FROM queue WHERE type = 'summary'")
    summary_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM queue")
    total_count = cursor.fetchone()[0]

    print("Queue statistics:")
    print(f"  Total items: {total_count}")
    print(f"  Summary items: {summary_count}")
    print(f"  YouTube items: {total_count - summary_count}")
    print()

    # Show sample summary items if any
    if summary_count > 0:
        cursor.execute("""
            SELECT id, title, type, week_year
            FROM queue
            WHERE type = 'summary'
            LIMIT 5
        """)
        samples = cursor.fetchall()

        print("Sample summary items in queue:")
        for item_id, title, item_type, week_year in samples:
            print(f"  [{item_id}] {title}")
            print(f"       type={item_type}, week_year={week_year}")

    conn.close()

    print()
    print("✅ Database schema is up to date!")
    return True


if __name__ == "__main__":
    success = check_queue_schema()
    sys.exit(0 if success else 1)
