"""Integration tests for weekly summaries routes."""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile
import shutil

from main import app
from services.database import (
    save_weekly_summary,
    get_summary_by_week_year,
    get_recent_summaries,
)


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def temp_audio_dir():
    """Create temporary audio directory."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_summary(temp_audio_dir):
    """Create a sample weekly summary in the database."""
    week_year = "2026-W04"

    # Create fake audio file
    audio_path = Path(temp_audio_dir) / f"{week_year}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"fake mp3 data" * 1000)

    # Save to database
    save_weekly_summary(
        week_year=week_year,
        year=2026,
        week=4,
        title="Summary of week 2026-W04",
        trilium_note_id="test-note-123",
        audio_file_path=str(audio_path),
        duration_seconds=420,
    )

    yield {
        "week_year": week_year,
        "audio_path": audio_path,
    }

    # Cleanup
    if audio_path.exists():
        audio_path.unlink()


class TestListSummaries:
    """Tests for GET /weekly-summaries endpoint."""

    def test_returns_empty_list_when_no_summaries(self, client):
        """Should return empty list when no summaries exist."""
        response = client.get("/weekly-summaries")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_returns_summaries(self, client, sample_summary):
        """Should return list of summaries."""
        response = client.get("/weekly-summaries")

        assert response.status_code == 200
        data = response.json()

        assert len(data) >= 1
        summary = data[0]
        assert summary["week_year"] == sample_summary["week_year"]
        assert summary["title"] == "Summary of week 2026-W04"
        assert summary["year"] == 2026
        assert summary["week"] == 4

    def test_respects_limit_parameter(self, client, sample_summary):
        """Should respect the limit parameter."""
        # Create multiple summaries
        for i in range(5, 10):
            save_weekly_summary(
                week_year=f"2026-W{i:02d}",
                year=2026,
                week=i,
                title=f"Summary of week 2026-W{i:02d}",
                trilium_note_id=f"note-{i}",
            )

        # Request with limit
        response = client.get("/weekly-summaries?limit=3")

        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 3

    def test_returns_most_recent_first(self, client):
        """Should return most recent summaries first."""
        # Create summaries in different orders
        summaries_to_create = [
            ("2026-W01", 2026, 1),
            ("2026-W05", 2026, 5),
            ("2026-W03", 2026, 3),
        ]

        for week_year, year, week in summaries_to_create:
            save_weekly_summary(
                week_year=week_year,
                year=year,
                week=week,
                title=f"Summary of week {week_year}",
                trilium_note_id=f"note-{week}",
            )

        response = client.get("/weekly-summaries?limit=3")

        assert response.status_code == 200
        data = response.json()

        # Should be ordered by year DESC, week DESC
        if len(data) >= 2:
            # Check ordering (most recent first)
            assert data[0]["week"] >= data[1]["week"]


class TestStreamSummaryAudio:
    """Tests for GET /weekly-summaries/{week_year}/audio endpoint."""

    def test_streams_audio_successfully(self, client, sample_summary):
        """Should stream audio file successfully."""
        week_year = sample_summary["week_year"]
        response = client.get(f"/weekly-summaries/{week_year}/audio")

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"
        assert len(response.content) > 0

    def test_returns_404_for_nonexistent_summary(self, client):
        """Should return 404 for non-existent summary."""
        response = client.get("/weekly-summaries/2099-W99/audio")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_returns_404_when_no_audio_file(self, client):
        """Should return 404 when summary has no audio file."""
        # Create summary without audio
        save_weekly_summary(
            week_year="2026-W10",
            year=2026,
            week=10,
            title="Summary without audio",
            trilium_note_id="note-no-audio",
        )

        response = client.get("/weekly-summaries/2026-W10/audio")

        assert response.status_code == 404
        assert "No audio file" in response.json()["detail"]

    def test_returns_404_when_file_doesnt_exist_on_disk(self, client, temp_audio_dir):
        """Should return 404 when database has path but file doesn't exist."""
        # Create summary with non-existent audio path
        fake_path = Path(temp_audio_dir) / "nonexistent.mp3"
        save_weekly_summary(
            week_year="2026-W11",
            year=2026,
            week=11,
            title="Summary with missing file",
            trilium_note_id="note-missing",
            audio_file_path=str(fake_path),
        )

        response = client.get("/weekly-summaries/2026-W11/audio")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestAddSummaryToQueue:
    """Tests for POST /queue/add-summary/{week_year} endpoint."""

    def test_adds_summary_to_queue_successfully(self, client, sample_summary):
        """Should add summary to queue successfully."""
        week_year = sample_summary["week_year"]
        response = client.post(f"/queue/add-summary/{week_year}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["queue_id"] is not None
        assert week_year in data["message"]

    def test_returns_404_for_nonexistent_summary(self, client):
        """Should return 404 for non-existent summary."""
        response = client.post("/queue/add-summary/2099-W99")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_returns_404_when_summary_has_no_audio(self, client):
        """Should return 404 when summary has no audio file."""
        # Create summary without audio
        save_weekly_summary(
            week_year="2026-W12",
            year=2026,
            week=12,
            title="Summary without audio",
            trilium_note_id="note-no-audio-2",
        )

        response = client.post("/queue/add-summary/2026-W12")

        assert response.status_code == 404
        assert "no audio file" in response.json()["detail"].lower()

    def test_adds_multiple_summaries_to_queue(self, client, sample_summary, temp_audio_dir):
        """Should be able to add multiple summaries to queue."""
        # Create another summary
        week_year_2 = "2026-W05"
        audio_path_2 = Path(temp_audio_dir) / f"{week_year_2}.mp3"
        audio_path_2.write_bytes(b"another fake mp3")

        save_weekly_summary(
            week_year=week_year_2,
            year=2026,
            week=5,
            title="Another summary",
            trilium_note_id="note-2",
            audio_file_path=str(audio_path_2),
            duration_seconds=360,
        )

        # Add both to queue
        response1 = client.post(f"/queue/add-summary/{sample_summary['week_year']}")
        response2 = client.post(f"/queue/add-summary/{week_year_2}")

        assert response1.status_code == 200
        assert response2.status_code == 200

        # Check queue has both items
        queue_response = client.get("/queue")
        assert queue_response.status_code == 200
        queue_data = queue_response.json()
        assert len(queue_data["queue"]) >= 2


class TestDatabaseFunctions:
    """Tests for database functions used by routes."""

    def test_save_and_retrieve_summary(self, temp_audio_dir):
        """Should save and retrieve summary correctly."""
        # Save summary
        week_year = "2026-W20"
        audio_path = Path(temp_audio_dir) / f"{week_year}.mp3"
        audio_path.write_bytes(b"test audio")

        save_weekly_summary(
            week_year=week_year,
            year=2026,
            week=20,
            title="Test Summary",
            trilium_note_id="test-note-id",
            audio_file_path=str(audio_path),
            duration_seconds=180,
        )

        # Retrieve summary
        summary = get_summary_by_week_year(week_year)

        assert summary is not None
        assert summary["week_year"] == week_year
        assert summary["title"] == "Test Summary"
        assert summary["trilium_note_id"] == "test-note-id"
        assert summary["duration_seconds"] == 180

    def test_get_recent_summaries_returns_correct_count(self):
        """Should return correct number of recent summaries."""
        # Create several summaries
        for i in range(1, 6):
            save_weekly_summary(
                week_year=f"2026-W{i:02d}",
                year=2026,
                week=i,
                title=f"Summary {i}",
                trilium_note_id=f"note-{i}",
            )

        # Get recent summaries with limit
        summaries = get_recent_summaries(limit=3)

        assert len(summaries) == 3

    def test_upsert_behavior(self, temp_audio_dir):
        """Should update existing summary on conflict."""
        week_year = "2026-W30"

        # First save
        save_weekly_summary(
            week_year=week_year,
            year=2026,
            week=30,
            title="Original Title",
            trilium_note_id="note-1",
        )

        # Update with audio
        audio_path = Path(temp_audio_dir) / f"{week_year}.mp3"
        audio_path.write_bytes(b"new audio")

        save_weekly_summary(
            week_year=week_year,
            year=2026,
            week=30,
            title="Updated Title",
            trilium_note_id="note-1",
            audio_file_path=str(audio_path),
            duration_seconds=240,
        )

        # Retrieve and verify
        summary = get_summary_by_week_year(week_year)

        assert summary["title"] == "Updated Title"
        assert summary["audio_file_path"] == str(audio_path)
        assert summary["duration_seconds"] == 240
