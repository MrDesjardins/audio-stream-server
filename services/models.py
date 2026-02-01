"""Data models for database entities and API responses."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PlayHistoryItem:
    """Represents a play history record."""

    id: int
    youtube_id: str
    title: str
    channel: Optional[str]
    thumbnail_url: Optional[str]
    play_count: int
    created_at: str  # ISO 8601 format
    last_played_at: str  # ISO 8601 format

    @classmethod
    def from_db_row(cls, row) -> "PlayHistoryItem":
        """Create instance from database row."""
        return cls(
            id=row["id"],
            youtube_id=row["youtube_id"],
            title=row["title"],
            channel=row["channel"],
            thumbnail_url=row["thumbnail_url"],
            play_count=row["play_count"],
            created_at=row["created_at"],
            last_played_at=row["last_played_at"],
        )

    def to_dict(self) -> dict:
        """Convert to dictionary (for backward compatibility)."""
        return {
            "id": self.id,
            "youtube_id": self.youtube_id,
            "title": self.title,
            "channel": self.channel,
            "thumbnail_url": self.thumbnail_url,
            "play_count": self.play_count,
            "created_at": self.created_at,
            "last_played_at": self.last_played_at,
        }


@dataclass
class QueueItem:
    """Represents a queue item."""

    id: int
    youtube_id: str
    title: str
    channel: Optional[str]
    thumbnail_url: Optional[str]
    position: int
    created_at: str  # ISO 8601 format
    type: str = "youtube"  # Type of queue item (youtube or summary)
    week_year: Optional[str] = None  # Week identifier for summary items

    @classmethod
    def from_db_row(cls, row) -> "QueueItem":
        """Create instance from database row."""
        return cls(
            id=row["id"],
            youtube_id=row["youtube_id"],
            title=row["title"],
            channel=row["channel"],
            thumbnail_url=row["thumbnail_url"],
            position=row["position"],
            created_at=row["created_at"],
            type=row["type"] or "youtube",
            week_year=row["week_year"],
        )

    def to_dict(self) -> dict:
        """Convert to dictionary (for backward compatibility)."""
        result = {
            "id": self.id,
            "youtube_id": self.youtube_id,
            "title": self.title,
            "channel": self.channel,
            "thumbnail_url": self.thumbnail_url,
            "position": self.position,
            "created_at": self.created_at,
            "type": self.type,
        }
        if self.week_year:
            result["week_year"] = self.week_year
        return result


@dataclass
class VideoSummary:
    """Represents a video with its summary from Trilium."""

    video_id: str
    title: str
    summary: str
    note_url: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "video_id": self.video_id,
            "title": self.title,
            "summary": self.summary,
            "note_url": self.note_url,
        }


@dataclass
class WeeklySummary:
    """Represents a weekly summary record."""

    id: int
    week_year: str  # e.g., "2024-W01"
    year: int
    week: int
    title: str
    trilium_note_id: Optional[str]
    audio_file_path: Optional[str]
    duration_seconds: Optional[int]
    created_at: str  # ISO 8601 format
    audio_generated_at: Optional[str] = None  # ISO 8601 format

    @classmethod
    def from_db_row(cls, row) -> "WeeklySummary":
        """Create instance from database row."""
        return cls(
            id=row["id"],
            week_year=row["week_year"],
            year=row["year"],
            week=row["week"],
            title=row["title"],
            trilium_note_id=row["trilium_note_id"],
            audio_file_path=row["audio_file_path"],
            duration_seconds=row["duration_seconds"],
            created_at=row["created_at"],
            audio_generated_at=row["audio_generated_at"],
        )

    def to_dict(self) -> dict:
        """Convert to dictionary (for backward compatibility)."""
        result = {
            "id": self.id,
            "week_year": self.week_year,
            "year": self.year,
            "week": self.week,
            "title": self.title,
            "trilium_note_id": self.trilium_note_id,
            "audio_file_path": self.audio_file_path,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at,
        }
        if self.audio_generated_at:
            result["audio_generated_at"] = self.audio_generated_at
        return result


@dataclass
class BookInfo:
    """Represents book information for weekly summaries."""

    video_id: str
    title: str
    last_played_at: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        result = {"video_id": self.video_id, "title": self.title}
        if self.last_played_at:
            result["last_played_at"] = self.last_played_at
        return result


@dataclass
class VideoSuggestion:
    """Represents a suggested video."""

    video_id: str
    title: str
    channel: str
    duration: int
    youtube_url: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "video_id": self.video_id,
            "title": self.title,
            "channel": self.channel,
            "duration": self.duration,
            "youtube_url": self.youtube_url,
        }
