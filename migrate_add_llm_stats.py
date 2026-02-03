#!/usr/bin/env python3
"""
Database migration: Add LLM usage statistics table.

This migration adds a new table to track LLM API usage including:
- Token counts (prompt, response, reasoning)
- Provider and model information
- Feature/use case
- Associated video ID
- Timestamps and metadata
"""

import sqlite3
import logging
import sys
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DATABASE_PATH", "./audio_history.db")


def check_table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    """Check if a table exists in the database."""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    )
    return cursor.fetchone() is not None


def migrate():
    """Add LLM usage statistics table."""
    db_path = Path(DB_PATH)

    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        logger.info("Run the application first to create the database")
        return False

    logger.info(f"Migrating database: {db_path}")

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Check if llm_usage_stats table already exists
        if check_table_exists(cursor, "llm_usage_stats"):
            logger.info("Table 'llm_usage_stats' already exists, skipping migration")
            conn.close()
            return True

        logger.info("Creating llm_usage_stats table...")

        # Create the LLM usage statistics table
        cursor.execute("""
            CREATE TABLE llm_usage_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                feature TEXT NOT NULL,
                prompt_tokens INTEGER,
                response_tokens INTEGER,
                reasoning_tokens INTEGER,
                total_tokens INTEGER,
                video_id TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL
            )
        """)

        logger.info("Creating indexes...")

        # Create indexes for common queries
        cursor.execute("""
            CREATE INDEX idx_llm_timestamp
            ON llm_usage_stats(timestamp DESC)
        """)

        cursor.execute("""
            CREATE INDEX idx_llm_provider_model
            ON llm_usage_stats(provider, model)
        """)

        cursor.execute("""
            CREATE INDEX idx_llm_feature
            ON llm_usage_stats(feature)
        """)

        conn.commit()
        logger.info("✓ Migration completed successfully")

        # Show table info
        cursor.execute("PRAGMA table_info(llm_usage_stats)")
        columns = cursor.fetchall()
        logger.info(f"Table created with {len(columns)} columns:")
        for col in columns:
            logger.info(f"  - {col[1]} ({col[2]})")

        conn.close()
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("LLM Usage Statistics Table Migration")
    logger.info("=" * 60)

    success = migrate()

    if success:
        logger.info("\n✓ Migration completed successfully!")
        logger.info("\nYou can now track LLM usage with:")
        logger.info("  - log_llm_usage() to log API calls")
        logger.info("  - get_llm_usage_stats() to query usage")
        logger.info("  - get_llm_usage_summary() to get aggregated stats")
        sys.exit(0)
    else:
        logger.error("\n✗ Migration failed")
        sys.exit(1)
