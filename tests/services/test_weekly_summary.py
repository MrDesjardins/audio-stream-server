"""Tests for weekly summary service."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from services.weekly_summary import (
    get_week_number,
    get_books_from_last_week,
    get_books_from_trilium_last_week,
    fetch_book_summaries,
    generate_weekly_summary_openai,
    generate_weekly_summary_gemini,
    create_weekly_summary_note,
    generate_and_save_weekly_summary,
)


class TestGetWeekNumber:
    """Tests for get_week_number function."""

    def test_get_week_number_returns_year_and_week(self):
        """Should return tuple of (year, week_number)."""
        date = datetime(2026, 1, 15)  # Mid-January 2026
        year, week = get_week_number(date)

        assert isinstance(year, int)
        assert isinstance(week, int)
        assert year == 2026
        assert 1 <= week <= 53

    def test_get_week_number_handles_year_boundary(self):
        """Should handle dates near year boundary correctly."""
        # Jan 1, 2026 might be week 53 of 2025 or week 1 of 2026
        date = datetime(2026, 1, 1)
        year, week = get_week_number(date)

        assert year in [2025, 2026]
        assert 1 <= week <= 53


class TestGetBooksFromLastWeek:
    """Tests for get_books_from_last_week function."""

    @patch("services.weekly_summary.get_history")
    def test_returns_books_from_last_7_days(self, mock_get_history):
        """Should return only books played in last 7 days."""
        now = datetime.now()
        recent = (now - timedelta(days=3)).isoformat()
        old = (now - timedelta(days=10)).isoformat()

        mock_get_history.return_value = [
            {
                "youtube_id": "recent1",
                "title": "Recent Book 1",
                "last_played_at": recent,
            },
            {"youtube_id": "old1", "title": "Old Book", "last_played_at": old},
            {
                "youtube_id": "recent2",
                "title": "Recent Book 2",
                "last_played_at": recent,
            },
        ]

        books = get_books_from_last_week()

        assert len(books) == 2
        assert books[0]["video_id"] == "recent1"
        assert books[1]["video_id"] == "recent2"

    @patch("services.weekly_summary.get_history")
    def test_handles_empty_history(self, mock_get_history):
        """Should return empty list when no history."""
        mock_get_history.return_value = []

        books = get_books_from_last_week()

        assert len(books) == 0

    @patch("services.weekly_summary.get_history")
    def test_handles_timezone_aware_dates(self, mock_get_history):
        """Should handle timezone-aware datetime strings."""
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(days=2)).isoformat()

        mock_get_history.return_value = [
            {"youtube_id": "vid1", "title": "Book 1", "last_played_at": recent},
        ]

        books = get_books_from_last_week()

        assert len(books) == 1

    @patch("services.weekly_summary.get_history")
    def test_skips_invalid_dates(self, mock_get_history):
        """Should skip entries with invalid dates."""
        now = datetime.now()
        valid = (now - timedelta(days=2)).isoformat()

        mock_get_history.return_value = [
            {"youtube_id": "valid", "title": "Valid", "last_played_at": valid},
            {
                "youtube_id": "invalid",
                "title": "Invalid",
                "last_played_at": "not-a-date",
            },
        ]

        books = get_books_from_last_week()

        assert len(books) == 1
        assert books[0]["video_id"] == "valid"


class TestGetBooksFromTriliumLastWeek:
    """Tests for get_books_from_trilium_last_week function."""

    @patch("services.weekly_summary.config")
    @patch("services.weekly_summary.get_httpx_client")
    def test_searches_trilium_for_recent_notes(self, mock_client_getter, mock_config):
        """Should search Trilium for notes with youtube_id from last 7 days."""
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        # Mock search response
        search_response = Mock()
        search_response.status_code = 200
        search_response.json.return_value = {
            "results": [
                {"noteId": "note1", "title": "Book 1"},
                {"noteId": "note2", "title": "Book 2"},
            ]
        }

        # Mock attribute responses
        attr_response1 = Mock()
        attr_response1.status_code = 200
        attr_response1.json.return_value = [
            {"name": "youtube_id", "value": "vid1"},
        ]

        attr_response2 = Mock()
        attr_response2.status_code = 200
        attr_response2.json.return_value = [
            {"name": "youtube_id", "value": "vid2"},
        ]

        mock_client = Mock()
        mock_client.get.side_effect = [search_response, attr_response1, attr_response2]
        mock_client_getter.return_value = mock_client

        books = get_books_from_trilium_last_week()

        assert len(books) == 2
        assert books[0]["video_id"] == "vid1"
        assert books[0]["title"] == "Book 1"
        assert books[1]["video_id"] == "vid2"

    @patch("services.weekly_summary.config")
    @patch("services.weekly_summary.get_httpx_client")
    def test_handles_empty_search_results(self, mock_client_getter, mock_config):
        """Should return empty list when no notes found."""
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        search_response = Mock()
        search_response.status_code = 200
        search_response.json.return_value = {"results": []}

        mock_client = Mock()
        mock_client.get.return_value = search_response
        mock_client_getter.return_value = mock_client

        books = get_books_from_trilium_last_week()

        assert len(books) == 0

    @patch("services.weekly_summary.config")
    @patch("services.weekly_summary.get_httpx_client")
    def test_handles_trilium_error(self, mock_client_getter, mock_config):
        """Should return empty list on Trilium API error."""
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        search_response = Mock()
        search_response.status_code = 500
        search_response.text = "Internal Server Error"

        mock_client = Mock()
        mock_client.get.return_value = search_response
        mock_client_getter.return_value = mock_client

        books = get_books_from_trilium_last_week()

        assert len(books) == 0


class TestFetchBookSummaries:
    """Tests for fetch_book_summaries function."""

    @patch("services.weekly_summary.get_note_content")
    @patch("services.weekly_summary.check_video_exists")
    @patch("services.weekly_summary.config")
    def test_fetches_summaries_from_trilium(
        self, mock_config, mock_check_video, mock_get_content
    ):
        """Should fetch summaries for each book."""
        mock_config.trilium_url = "http://localhost:8080"

        books = [
            {"video_id": "vid1", "title": "Book 1"},
            {"video_id": "vid2", "title": "Book 2"},
        ]

        mock_check_video.side_effect = [
            {"noteId": "note1", "url": "http://localhost:8080/#root/note1"},
            {"noteId": "note2", "url": "http://localhost:8080/#root/note2"},
        ]

        mock_get_content.side_effect = [
            "<h3>Summary</h3><p>This is summary 1</p>",
            "<h3>Summary</h3><p>This is summary 2</p>",
        ]

        summaries = fetch_book_summaries(books)

        assert len(summaries) == 2
        assert summaries[0]["video_id"] == "vid1"
        assert "summary 1" in summaries[0]["summary"]
        assert summaries[1]["video_id"] == "vid2"

    @patch("services.weekly_summary.check_video_exists")
    def test_skips_books_without_trilium_note(self, mock_check_video):
        """Should skip books that don't have Trilium notes."""
        books = [
            {"video_id": "vid1", "title": "Book 1"},
            {"video_id": "vid2", "title": "Book 2"},
        ]

        mock_check_video.side_effect = [
            {"noteId": "note1", "url": "url1"},
            None,  # vid2 has no note
        ]

        with patch("services.weekly_summary.get_note_content", return_value="Summary"):
            summaries = fetch_book_summaries(books)

        assert len(summaries) == 1
        assert summaries[0]["video_id"] == "vid1"


class TestGenerateWeeklySummaryOpenAI:
    """Tests for generate_weekly_summary_openai function."""

    @patch("services.weekly_summary.get_openai_client")
    def test_generates_summary_with_openai(self, mock_client_getter):
        """Should call OpenAI API and return summary."""
        summaries = [
            {"title": "Book 1", "summary": "Summary 1"},
            {"title": "Book 2", "summary": "Summary 2"},
        ]

        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "## Overview\nWeekly summary content"

        mock_client = Mock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_client_getter.return_value = mock_client

        result = generate_weekly_summary_openai(summaries)

        assert result == "## Overview\nWeekly summary content"
        mock_client.chat.completions.create.assert_called_once()

    @patch("services.weekly_summary.get_openai_client")
    def test_handles_openai_error(self, mock_client_getter):
        """Should return None on OpenAI API error."""
        summaries = [{"title": "Book 1", "summary": "Summary 1"}]

        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        mock_client_getter.return_value = mock_client

        result = generate_weekly_summary_openai(summaries)

        assert result is None


class TestGenerateWeeklySummaryGemini:
    """Tests for generate_weekly_summary_gemini function."""

    @patch("services.weekly_summary.genai.Client")
    @patch("services.weekly_summary.config")
    def test_generates_summary_with_gemini(self, mock_config, mock_gemini_client):
        """Should call Gemini API and return summary."""
        mock_config.gemini_api_key = "test-key"

        summaries = [
            {"title": "Book 1", "summary": "Summary 1"},
            {"title": "Book 2", "summary": "Summary 2"},
        ]

        mock_response = Mock()
        mock_response.text = "## Overview\nWeekly summary from Gemini"

        mock_client_instance = Mock()
        mock_client_instance.models.generate_content.return_value = mock_response
        mock_gemini_client.return_value = mock_client_instance

        result = generate_weekly_summary_gemini(summaries)

        assert result == "## Overview\nWeekly summary from Gemini"

    @patch("services.weekly_summary.genai.Client")
    @patch("services.weekly_summary.config")
    def test_handles_gemini_error(self, mock_config, mock_gemini_client):
        """Should return None on Gemini API error."""
        mock_config.gemini_api_key = "test-key"

        summaries = [{"title": "Book 1", "summary": "Summary 1"}]

        mock_client_instance = Mock()
        mock_client_instance.models.generate_content.side_effect = Exception(
            "API Error"
        )
        mock_gemini_client.return_value = mock_client_instance

        result = generate_weekly_summary_gemini(summaries)

        assert result is None


class TestCreateWeeklySummaryNote:
    """Tests for create_weekly_summary_note function."""

    @patch("services.weekly_summary.config")
    @patch("services.weekly_summary.get_httpx_client")
    def test_creates_trilium_note(self, mock_client_getter, mock_config):
        """Should create Trilium note with summary."""
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"
        mock_config.trilium_parent_note_id = "parent123"

        summary_content = "## Overview\nWeekly summary"
        book_links = [
            {"title": "Book 1", "note_url": "url1"},
            {"title": "Book 2", "note_url": "url2"},
        ]

        # Mock note creation response
        create_response = Mock()
        create_response.status_code = 201
        create_response.json.return_value = {"note": {"noteId": "weekly123"}}

        # Mock attribute creation response
        attr_response = Mock()
        attr_response.status_code = 201

        mock_client = Mock()
        mock_client.post.side_effect = [create_response, attr_response]
        mock_client_getter.return_value = mock_client

        result = create_weekly_summary_note(summary_content, book_links, 2026, 5)

        assert result is not None
        assert result["noteId"] == "weekly123"
        assert "weekly123" in result["url"]

    @patch("services.weekly_summary.config")
    @patch("services.weekly_summary.get_httpx_client")
    def test_handles_trilium_create_error(self, mock_client_getter, mock_config):
        """Should return None on Trilium note creation error."""
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"
        mock_config.trilium_parent_note_id = "parent123"

        create_response = Mock()
        create_response.status_code = 500
        create_response.text = "Internal Server Error"

        mock_client = Mock()
        mock_client.post.return_value = create_response
        mock_client_getter.return_value = mock_client

        result = create_weekly_summary_note("Summary", [], 2026, 5)

        assert result is None


class TestGenerateAndSaveWeeklySummary:
    """Tests for generate_and_save_weekly_summary function."""

    @patch("services.weekly_summary.save_weekly_summary")
    @patch("services.weekly_summary.get_summary_by_week_year")
    @patch("services.weekly_summary.create_weekly_summary_note")
    @patch("services.weekly_summary.generate_weekly_summary_openai")
    @patch("services.weekly_summary.fetch_book_summaries")
    @patch("services.weekly_summary.get_books_from_trilium_last_week")
    @patch("services.weekly_summary.config")
    def test_full_workflow_success(
        self,
        mock_config,
        mock_get_books_trilium,
        mock_fetch_summaries,
        mock_generate_summary,
        mock_create_note,
        mock_get_existing_summary,
        mock_save_summary,
    ):
        """Should complete full weekly summary workflow."""
        mock_config.summary_provider = "openai"
        mock_config.tts_enabled = False  # Disable TTS for this test
        mock_get_existing_summary.return_value = None  # No existing summary

        # Mock books from Trilium
        mock_get_books_trilium.return_value = [
            {"video_id": "vid1", "title": "Book 1"},
            {"video_id": "vid2", "title": "Book 2"},
        ]

        # Mock summaries
        mock_fetch_summaries.return_value = [
            {
                "video_id": "vid1",
                "title": "Book 1",
                "summary": "Summary 1",
                "note_url": "url1",
            },
            {
                "video_id": "vid2",
                "title": "Book 2",
                "summary": "Summary 2",
                "note_url": "url2",
            },
        ]

        # Mock AI summary
        mock_generate_summary.return_value = "## Overview\nWeekly summary"

        # Mock note creation
        mock_create_note.return_value = {"noteId": "weekly123", "url": "url"}

        result = generate_and_save_weekly_summary()

        assert result is not None
        assert result["noteId"] == "weekly123"
        mock_save_summary.assert_called_once()

    @patch("services.weekly_summary.get_summary_by_week_year")
    @patch("services.weekly_summary.get_books_from_trilium_last_week")
    @patch("services.weekly_summary.get_books_from_last_week")
    def test_falls_back_to_database_when_trilium_fails(
        self, mock_get_books_db, mock_get_books_trilium, mock_get_existing_summary
    ):
        """Should fallback to database when Trilium search fails."""
        mock_get_existing_summary.return_value = None  # No existing summary
        mock_get_books_trilium.return_value = []  # Trilium returns nothing
        mock_get_books_db.return_value = []  # Database also empty

        result = generate_and_save_weekly_summary()

        assert result is None
        mock_get_books_db.assert_called_once()

    @patch("services.weekly_summary.get_summary_by_week_year")
    @patch("services.weekly_summary.fetch_book_summaries")
    @patch("services.weekly_summary.get_books_from_trilium_last_week")
    def test_skips_when_no_summaries_found(
        self, mock_get_books, mock_fetch_summaries, mock_get_existing_summary
    ):
        """Should skip when no summaries found in Trilium."""
        mock_get_existing_summary.return_value = None  # No existing summary
        mock_get_books.return_value = [{"video_id": "vid1", "title": "Book 1"}]
        mock_fetch_summaries.return_value = []  # No summaries

        result = generate_and_save_weekly_summary()

        assert result is None

    @patch("services.weekly_summary.save_weekly_summary")
    @patch("services.weekly_summary.create_weekly_summary_note")
    @patch("services.weekly_summary.generate_weekly_summary_openai")
    @patch("services.weekly_summary.fetch_book_summaries")
    @patch("services.weekly_summary.get_books_from_trilium_last_week")
    @patch("services.weekly_summary.get_httpx_client")
    @patch("services.weekly_summary.get_summary_by_week_year")
    @patch("services.weekly_summary.config")
    def test_regenerates_when_trilium_note_missing(
        self,
        mock_config,
        mock_get_existing_summary,
        mock_httpx_client,
        mock_get_books,
        mock_fetch_summaries,
        mock_generate_summary,
        mock_create_note,
        mock_save_summary,
    ):
        """Should regenerate summary when database entry exists but Trilium note is 404."""
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"
        mock_config.summary_provider = "openai"
        mock_config.tts_enabled = False

        # Mock existing summary in database with a note ID that doesn't exist
        mock_get_existing_summary.return_value = {
            "week_year": "2026-W05",
            "trilium_note_id": "missing-note-id",
            "title": "Old summary",
        }

        # Mock 404 response when checking if note exists
        mock_404_response = Mock()
        mock_404_response.status_code = 404

        mock_client = Mock()
        mock_client.get.return_value = mock_404_response
        mock_httpx_client.return_value = mock_client

        # Mock the regeneration workflow
        mock_get_books.return_value = [{"video_id": "vid1", "title": "Book 1"}]
        mock_fetch_summaries.return_value = [
            {
                "video_id": "vid1",
                "title": "Book 1",
                "summary": "Summary 1",
                "note_url": "url1",
            }
        ]
        mock_generate_summary.return_value = "## New Summary"
        mock_create_note.return_value = {
            "noteId": "new-note-123",
            "url": "http://localhost:8080/#root/new-note-123",
        }

        result = generate_and_save_weekly_summary()

        # Should regenerate the summary instead of using the missing one
        assert result is not None
        assert result["noteId"] == "new-note-123"
        mock_create_note.assert_called_once()  # Should create a new note
