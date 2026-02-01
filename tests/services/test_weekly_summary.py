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
from services.models import PlayHistoryItem, WeeklySummary


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


class TestIsPlayedWithinLastWeek:
    """Tests for _is_played_within_last_week helper function."""

    def test_returns_book_info_when_played_recently(self):
        """Should return book dict when played within last week."""
        from services.weekly_summary import _is_played_within_last_week

        now = datetime.now()
        recent = (now - timedelta(days=3)).isoformat()
        cutoff = now - timedelta(days=7)

        item = PlayHistoryItem(
            id=1,
            youtube_id="vid1",
            title="Recent Book",
            channel=None,
            thumbnail_url=None,
            play_count=1,
            created_at="2024-01-01T00:00:00",
            last_played_at=recent,
        )

        result = _is_played_within_last_week(item, cutoff)

        assert result is not None
        assert result["video_id"] == "vid1"
        assert result["title"] == "Recent Book"

    def test_returns_none_when_played_too_long_ago(self):
        """Should return None when played before cutoff."""
        from services.weekly_summary import _is_played_within_last_week

        now = datetime.now()
        old = (now - timedelta(days=10)).isoformat()
        cutoff = now - timedelta(days=7)

        item = PlayHistoryItem(
            id=1,
            youtube_id="vid1",
            title="Old Book",
            channel=None,
            thumbnail_url=None,
            play_count=1,
            created_at="2024-01-01T00:00:00",
            last_played_at=old,
        )

        result = _is_played_within_last_week(item, cutoff)

        assert result is None

    def test_handles_invalid_date_format(self):
        """Should return None on invalid date format."""
        from services.weekly_summary import _is_played_within_last_week

        now = datetime.now()
        cutoff = now - timedelta(days=7)

        item = PlayHistoryItem(
            id=1,
            youtube_id="vid1",
            title="Book",
            channel=None,
            thumbnail_url=None,
            play_count=1,
            created_at="2024-01-01T00:00:00",
            last_played_at="invalid-date",
        )

        result = _is_played_within_last_week(item, cutoff)

        assert result is None


class TestGetBooksFromLastWeek:
    """Tests for get_books_from_last_week function."""

    @patch("services.weekly_summary.get_history")
    def test_returns_books_from_last_7_days(self, mock_get_history):
        """Should return only books played in last 7 days."""
        now = datetime.now()
        recent = (now - timedelta(days=3)).isoformat()
        old = (now - timedelta(days=10)).isoformat()

        mock_get_history.return_value = [
            PlayHistoryItem(
                id=1,
                youtube_id="recent1",
                title="Recent Book 1",
                channel=None,
                thumbnail_url=None,
                play_count=1,
                created_at="2024-01-01T00:00:00",
                last_played_at=recent,
            ),
            PlayHistoryItem(
                id=2,
                youtube_id="old1",
                title="Old Book",
                channel=None,
                thumbnail_url=None,
                play_count=1,
                created_at="2024-01-01T00:00:00",
                last_played_at=old,
            ),
            PlayHistoryItem(
                id=3,
                youtube_id="recent2",
                title="Recent Book 2",
                channel=None,
                thumbnail_url=None,
                play_count=1,
                created_at="2024-01-01T00:00:00",
                last_played_at=recent,
            ),
        ]

        books = get_books_from_last_week()

        assert len(books) == 2
        assert books[0]["video_id"] == "recent1"
        assert books[1]["video_id"] == "recent2"

    @patch("services.weekly_summary.get_history")
    def test_handles_exception_gracefully(self, mock_get_history):
        """Should return empty list on exception."""
        mock_get_history.side_effect = Exception("Database error")

        books = get_books_from_last_week()

        assert books == []

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
            PlayHistoryItem(
                id=1,
                youtube_id="vid1",
                title="Book 1",
                channel=None,
                thumbnail_url=None,
                play_count=1,
                created_at="2024-01-01T00:00:00",
                last_played_at=recent,
            ),
        ]

        books = get_books_from_last_week()

        assert len(books) == 1

    @patch("services.weekly_summary.get_history")
    def test_skips_invalid_dates(self, mock_get_history):
        """Should skip entries with invalid dates."""
        now = datetime.now()
        valid = (now - timedelta(days=2)).isoformat()

        mock_get_history.return_value = [
            PlayHistoryItem(
                id=1,
                youtube_id="valid",
                title="Valid",
                channel=None,
                thumbnail_url=None,
                play_count=1,
                created_at="2024-01-01T00:00:00",
                last_played_at=valid,
            ),
            PlayHistoryItem(
                id=2,
                youtube_id="invalid",
                title="Invalid",
                channel=None,
                thumbnail_url=None,
                play_count=1,
                created_at="2024-01-01T00:00:00",
                last_played_at="not-a-date",
            ),
        ]

        books = get_books_from_last_week()

        assert len(books) == 1
        assert books[0]["video_id"] == "valid"


class TestFetchYoutubeIdFromNote:
    """Tests for _fetch_youtube_id_from_note helper function."""

    @patch("services.weekly_summary.get_httpx_client")
    @patch("services.weekly_summary.config")
    def test_successfully_fetches_youtube_id(self, mock_config, mock_client_getter):
        """Should fetch YouTube ID from note attributes."""
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        attr_response = Mock()
        attr_response.status_code = 200
        attr_response.json.return_value = [
            {"name": "youtube_id", "value": "test_vid_123"},
            {"name": "other_attr", "value": "other_value"},
        ]

        mock_client = Mock()
        mock_client.get.return_value = attr_response
        mock_client_getter.return_value = mock_client

        from services.weekly_summary import _fetch_youtube_id_from_note

        result = _fetch_youtube_id_from_note(
            {"noteId": "note123", "title": "Test Book"}
        )

        assert result is not None
        assert result["video_id"] == "test_vid_123"
        assert result["title"] == "Test Book"

    @patch("services.weekly_summary.get_httpx_client")
    @patch("services.weekly_summary.config")
    def test_returns_none_when_no_youtube_id_attribute(
        self, mock_config, mock_client_getter
    ):
        """Should return None when youtube_id attribute not found."""
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        attr_response = Mock()
        attr_response.status_code = 200
        attr_response.json.return_value = [
            {"name": "other_attr", "value": "other_value"},
        ]

        mock_client = Mock()
        mock_client.get.return_value = attr_response
        mock_client_getter.return_value = mock_client

        from services.weekly_summary import _fetch_youtube_id_from_note

        result = _fetch_youtube_id_from_note(
            {"noteId": "note123", "title": "Test Book"}
        )

        assert result is None

    @patch("services.weekly_summary.get_httpx_client")
    @patch("services.weekly_summary.config")
    def test_returns_none_when_youtube_id_value_empty(
        self, mock_config, mock_client_getter
    ):
        """Should return None when youtube_id value is empty."""
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        attr_response = Mock()
        attr_response.status_code = 200
        attr_response.json.return_value = [
            {"name": "youtube_id", "value": ""},  # Empty value
        ]

        mock_client = Mock()
        mock_client.get.return_value = attr_response
        mock_client_getter.return_value = mock_client

        from services.weekly_summary import _fetch_youtube_id_from_note

        result = _fetch_youtube_id_from_note(
            {"noteId": "note123", "title": "Test Book"}
        )

        assert result is None

    @patch("services.weekly_summary.get_httpx_client")
    @patch("services.weekly_summary.config")
    def test_handles_http_error(self, mock_config, mock_client_getter):
        """Should return None on HTTP error."""
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        mock_client = Mock()
        mock_client.get.side_effect = Exception("HTTP Error")
        mock_client_getter.return_value = mock_client

        from services.weekly_summary import _fetch_youtube_id_from_note

        result = _fetch_youtube_id_from_note(
            {"noteId": "note123", "title": "Test Book"}
        )

        assert result is None


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

    @patch("services.weekly_summary.get_httpx_client")
    @patch("services.weekly_summary.config")
    def test_handles_exception_during_search(self, mock_config, mock_client_getter):
        """Should return empty list on exception."""
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        mock_client = Mock()
        mock_client.get.side_effect = Exception("Network error")
        mock_client_getter.return_value = mock_client

        books = get_books_from_trilium_last_week()

        assert len(books) == 0


class TestFetchSummaryForBook:
    """Tests for _fetch_summary_for_book helper function."""

    @patch("services.weekly_summary.get_note_content")
    @patch("services.weekly_summary.check_video_exists")
    @patch("services.weekly_summary.config")
    def test_successfully_fetches_summary(
        self, mock_config, mock_check_video, mock_get_content
    ):
        """Should fetch summary from Trilium note."""
        from services.weekly_summary import _fetch_summary_for_book

        mock_config.trilium_url = "http://localhost:8080"

        mock_check_video.return_value = {
            "noteId": "note123",
            "url": "http://localhost:8080/#root/note123",
        }
        mock_get_content.return_value = "<h3>Summary</h3><p>Test summary content</p>"

        book = {"video_id": "vid1", "title": "Test Book"}
        result = _fetch_summary_for_book(book)

        assert result is not None
        assert result["video_id"] == "vid1"
        assert result["title"] == "Test Book"
        assert "Test summary content" in result["summary"]
        assert result["note_url"] == "http://localhost:8080/#root/note123"

    @patch("services.weekly_summary.check_video_exists")
    def test_returns_none_when_note_not_found(self, mock_check_video):
        """Should return None when Trilium note doesn't exist."""
        from services.weekly_summary import _fetch_summary_for_book

        mock_check_video.return_value = None

        book = {"video_id": "vid1", "title": "Test Book"}
        result = _fetch_summary_for_book(book)

        assert result is None

    @patch("services.weekly_summary.get_note_content")
    @patch("services.weekly_summary.check_video_exists")
    @patch("services.weekly_summary.config")
    def test_returns_none_when_content_empty(
        self, mock_config, mock_check_video, mock_get_content
    ):
        """Should return None when note content is empty."""
        from services.weekly_summary import _fetch_summary_for_book

        mock_config.trilium_url = "http://localhost:8080"
        mock_check_video.return_value = {"noteId": "note123", "url": "url"}
        mock_get_content.return_value = ""

        book = {"video_id": "vid1", "title": "Test Book"}
        result = _fetch_summary_for_book(book)

        assert result is None

    @patch("services.weekly_summary.get_note_content")
    @patch("services.weekly_summary.check_video_exists")
    @patch("services.weekly_summary.config")
    def test_returns_none_when_summary_only_html_tags(
        self, mock_config, mock_check_video, mock_get_content
    ):
        """Should return None when content has only HTML tags (empty text)."""
        from services.weekly_summary import _fetch_summary_for_book

        mock_config.trilium_url = "http://localhost:8080"
        mock_check_video.return_value = {"noteId": "note123", "url": "url"}
        mock_get_content.return_value = "<p></p><div></div>"  # Only tags, no text

        book = {"video_id": "vid1", "title": "Test Book"}
        result = _fetch_summary_for_book(book)

        assert result is None

    @patch("services.weekly_summary.check_video_exists")
    def test_handles_exception_gracefully(self, mock_check_video):
        """Should return None on exception."""
        from services.weekly_summary import _fetch_summary_for_book

        mock_check_video.side_effect = Exception("Trilium error")

        book = {"video_id": "vid1", "title": "Test Book"}
        result = _fetch_summary_for_book(book)

        assert result is None


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

    @patch("services.weekly_summary.get_openai_client")
    def test_handles_empty_openai_response(self, mock_client_getter):
        """Should return None when OpenAI returns empty content."""
        summaries = [{"title": "Book 1", "summary": "Summary 1"}]

        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = None  # Empty content

        mock_client = Mock()
        mock_client.chat.completions.create.return_value = mock_response
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

    @patch("services.weekly_summary.genai.Client")
    @patch("services.weekly_summary.config")
    def test_handles_empty_gemini_response(self, mock_config, mock_gemini_client):
        """Should return None when Gemini returns empty text."""
        mock_config.gemini_api_key = "test-key"

        summaries = [{"title": "Book 1", "summary": "Summary 1"}]

        mock_response = Mock()
        mock_response.text = None  # Empty text

        mock_client_instance = Mock()
        mock_client_instance.models.generate_content.return_value = mock_response
        mock_gemini_client.return_value = mock_client_instance

        result = generate_weekly_summary_gemini(summaries)

        assert result is None


class TestVerifyTriliumNoteExists:
    """Tests for _verify_trilium_note_exists helper function."""

    @patch("services.weekly_summary.get_httpx_client")
    @patch("services.weekly_summary.config")
    def test_returns_true_when_note_exists(self, mock_config, mock_client_getter):
        """Should return True when note exists (200)."""
        from services.weekly_summary import _verify_trilium_note_exists

        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        response = Mock()
        response.status_code = 200

        mock_client = Mock()
        mock_client.get.return_value = response
        mock_client_getter.return_value = mock_client

        result = _verify_trilium_note_exists("note123")

        assert result is True

    @patch("services.weekly_summary.get_httpx_client")
    @patch("services.weekly_summary.config")
    def test_returns_false_when_note_not_found(self, mock_config, mock_client_getter):
        """Should return False when note is 404."""
        from services.weekly_summary import _verify_trilium_note_exists

        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        response = Mock()
        response.status_code = 404

        mock_client = Mock()
        mock_client.get.return_value = response
        mock_client_getter.return_value = mock_client

        result = _verify_trilium_note_exists("note123")

        assert result is False

    @patch("services.weekly_summary.get_httpx_client")
    @patch("services.weekly_summary.config")
    def test_returns_true_on_other_http_errors(self, mock_config, mock_client_getter):
        """Should return True on other HTTP errors (proceed anyway)."""
        from services.weekly_summary import _verify_trilium_note_exists

        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        response = Mock()
        response.status_code = 500

        mock_client = Mock()
        mock_client.get.return_value = response
        mock_client_getter.return_value = mock_client

        result = _verify_trilium_note_exists("note123")

        assert result is True

    @patch("services.weekly_summary.get_httpx_client")
    @patch("services.weekly_summary.config")
    def test_returns_true_on_exception(self, mock_config, mock_client_getter):
        """Should return True on exception (proceed anyway)."""
        from services.weekly_summary import _verify_trilium_note_exists

        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        mock_client = Mock()
        mock_client.get.side_effect = Exception("Network error")
        mock_client_getter.return_value = mock_client

        result = _verify_trilium_note_exists("note123")

        assert result is True


class TestCheckAudioAlreadyAttached:
    """Tests for _check_audio_already_attached helper function."""

    @patch("services.weekly_summary.get_httpx_client")
    @patch("services.weekly_summary.config")
    def test_returns_true_when_audio_attached(self, mock_config, mock_client_getter):
        """Should return True when audio file is attached."""
        from services.weekly_summary import _check_audio_already_attached

        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        response = Mock()
        response.status_code = 200
        response.json.return_value = [
            {"title": "2024-W01.mp3", "noteId": "audio123"},
            {"title": "other.txt", "noteId": "other123"},
        ]

        mock_client = Mock()
        mock_client.get.return_value = response
        mock_client_getter.return_value = mock_client

        result = _check_audio_already_attached("note123", "2024-W01.mp3")

        assert result is True

    @patch("services.weekly_summary.get_httpx_client")
    @patch("services.weekly_summary.config")
    def test_returns_false_when_audio_not_attached(
        self, mock_config, mock_client_getter
    ):
        """Should return False when audio file is not attached."""
        from services.weekly_summary import _check_audio_already_attached

        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        response = Mock()
        response.status_code = 200
        response.json.return_value = [
            {"title": "other.txt", "noteId": "other123"},
        ]

        mock_client = Mock()
        mock_client.get.return_value = response
        mock_client_getter.return_value = mock_client

        result = _check_audio_already_attached("note123", "2024-W01.mp3")

        assert result is False

    @patch("services.weekly_summary.get_httpx_client")
    @patch("services.weekly_summary.config")
    def test_returns_false_on_exception(self, mock_config, mock_client_getter):
        """Should return False on exception."""
        from services.weekly_summary import _check_audio_already_attached

        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"

        mock_client = Mock()
        mock_client.get.side_effect = Exception("Network error")
        mock_client_getter.return_value = mock_client

        result = _check_audio_already_attached("note123", "2024-W01.mp3")

        assert result is False


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

    @patch("services.weekly_summary.config")
    @patch("services.weekly_summary.get_httpx_client")
    def test_handles_missing_note_id_in_response(self, mock_client_getter, mock_config):
        """Should return None when noteId missing in response."""
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"
        mock_config.trilium_parent_note_id = "parent123"

        create_response = Mock()
        create_response.status_code = 201
        create_response.json.return_value = {"note": {}}  # Missing noteId

        mock_client = Mock()
        mock_client.post.return_value = create_response
        mock_client_getter.return_value = mock_client

        result = create_weekly_summary_note("Summary", [], 2026, 5)

        assert result is None

    @patch("services.weekly_summary.config")
    @patch("services.weekly_summary.get_httpx_client")
    def test_handles_attribute_creation_failure(self, mock_client_getter, mock_config):
        """Should still return result even if attribute creation fails."""
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"
        mock_config.trilium_parent_note_id = "parent123"

        create_response = Mock()
        create_response.status_code = 201
        create_response.json.return_value = {"note": {"noteId": "weekly123"}}

        attr_response = Mock()
        attr_response.status_code = 500
        attr_response.text = "Attribute creation failed"

        mock_client = Mock()
        mock_client.post.side_effect = [create_response, attr_response]
        mock_client_getter.return_value = mock_client

        result = create_weekly_summary_note("Summary", [], 2026, 5)

        assert result is not None
        assert result["noteId"] == "weekly123"

    @patch("services.weekly_summary.config")
    @patch("services.weekly_summary.get_httpx_client")
    def test_handles_exception_gracefully(self, mock_client_getter, mock_config):
        """Should return None on exception."""
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.trilium_etapi_token = "test-token"
        mock_config.trilium_parent_note_id = "parent123"

        mock_client = Mock()
        mock_client.post.side_effect = Exception("Network error")
        mock_client_getter.return_value = mock_client

        result = create_weekly_summary_note("Summary", [], 2026, 5)

        assert result is None


class TestGenerateAndAttachTts:
    """Tests for _generate_and_attach_tts helper function."""

    @patch("services.weekly_summary.config")
    def test_returns_immediately_when_tts_disabled(self, mock_config):
        """Should return note info without generating TTS when disabled."""
        from services.weekly_summary import _generate_and_attach_tts

        mock_config.tts_enabled = False
        mock_config.trilium_url = "http://localhost:8080"

        result = _generate_and_attach_tts(
            note_id="note123",
            week_year="2024-W01",
            year=2024,
            week=1,
            note_title="Summary of week 2024-W01",
        )

        assert result is not None
        assert result["noteId"] == "note123"
        assert "note123" in result["url"]

    @patch("services.weekly_summary.save_weekly_summary")
    @patch("services.weekly_summary.attach_audio_to_note")
    @patch("services.weekly_summary._check_audio_already_attached")
    @patch("services.weekly_summary.get_audio_duration")
    @patch("services.weekly_summary.expand_path")
    @patch("services.weekly_summary.config")
    def test_uses_existing_audio_file(
        self,
        mock_config,
        mock_expand_path,
        mock_get_duration,
        mock_check_attached,
        mock_attach,
        mock_save,
    ):
        """Should use existing audio file if it exists."""
        from services.weekly_summary import _generate_and_attach_tts

        mock_config.tts_enabled = True
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.get_weekly_summary_audio_path.return_value = "/tmp/2024-W01.mp3"

        # Mock existing file
        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_expand_path.return_value = mock_path

        mock_get_duration.return_value = 120.5
        mock_check_attached.return_value = False  # Not yet attached
        mock_attach.return_value = {"success": True}

        result = _generate_and_attach_tts(
            note_id="note123",
            week_year="2024-W01",
            year=2024,
            week=1,
            note_title="Summary of week 2024-W01",
        )

        assert result is not None
        assert result["noteId"] == "note123"
        mock_attach.assert_called_once()
        mock_save.assert_called_once()

    @patch("services.weekly_summary.save_weekly_summary")
    @patch("services.weekly_summary.attach_audio_to_note")
    @patch("services.weekly_summary._check_audio_already_attached")
    @patch("services.weekly_summary.save_audio_file")
    @patch("services.weekly_summary.generate_audio")
    @patch("services.weekly_summary.extract_summary_text_for_tts")
    @patch("services.weekly_summary.get_note_content")
    @patch("services.weekly_summary.expand_path")
    @patch("services.weekly_summary.config")
    def test_generates_new_audio_when_not_exists(
        self,
        mock_config,
        mock_expand_path,
        mock_get_content,
        mock_extract_text,
        mock_generate_audio,
        mock_save_audio,
        mock_check_attached,
        mock_attach,
        mock_save,
    ):
        """Should generate new audio when file doesn't exist."""
        from services.weekly_summary import _generate_and_attach_tts

        mock_config.tts_enabled = True
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.elevenlabs_voice_id = "voice123"
        mock_config.elevenlabs_api_key = "key123"
        mock_config.get_weekly_summary_audio_path.return_value = "/tmp/2024-W01.mp3"

        # Mock no existing file
        mock_path = Mock()
        mock_path.exists.return_value = False
        mock_expand_path.return_value = mock_path

        mock_get_content.return_value = "<h3>Summary</h3><p>Content here</p>"
        mock_extract_text.return_value = "This is a long summary content that exceeds 50 characters for TTS generation"
        mock_generate_audio.return_value = b"audio_data"
        mock_save_audio.return_value = 120.5
        mock_check_attached.return_value = False
        mock_attach.return_value = {"success": True}

        result = _generate_and_attach_tts(
            note_id="note123",
            week_year="2024-W01",
            year=2024,
            week=1,
            note_title="Summary of week 2024-W01",
        )

        assert result is not None
        assert result["noteId"] == "note123"
        mock_generate_audio.assert_called_once()
        mock_save_audio.assert_called_once()
        mock_attach.assert_called_once()
        mock_save.assert_called_once()

    @patch("services.weekly_summary.save_weekly_summary")
    @patch("services.weekly_summary._check_audio_already_attached")
    @patch("services.weekly_summary.get_audio_duration")
    @patch("services.weekly_summary.expand_path")
    @patch("services.weekly_summary.config")
    def test_skips_attach_when_already_attached(
        self,
        mock_config,
        mock_expand_path,
        mock_get_duration,
        mock_check_attached,
        mock_save,
    ):
        """Should skip attachment when audio already attached."""
        from services.weekly_summary import _generate_and_attach_tts

        mock_config.tts_enabled = True
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.get_weekly_summary_audio_path.return_value = "/tmp/2024-W01.mp3"

        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_expand_path.return_value = mock_path

        mock_get_duration.return_value = 120.5
        mock_check_attached.return_value = True  # Already attached

        result = _generate_and_attach_tts(
            note_id="note123",
            week_year="2024-W01",
            year=2024,
            week=1,
            note_title="Summary of week 2024-W01",
        )

        assert result is not None
        mock_save.assert_called_once()

    @patch("services.weekly_summary.get_note_content")
    @patch("services.weekly_summary.expand_path")
    @patch("services.weekly_summary.config")
    def test_returns_none_when_content_fetch_fails(
        self, mock_config, mock_expand_path, mock_get_content
    ):
        """Should return None when note content cannot be fetched."""
        from services.weekly_summary import _generate_and_attach_tts

        mock_config.tts_enabled = True
        mock_config.get_weekly_summary_audio_path.return_value = "/tmp/2024-W01.mp3"

        mock_path = Mock()
        mock_path.exists.return_value = False
        mock_expand_path.return_value = mock_path

        mock_get_content.return_value = None  # Content fetch fails

        result = _generate_and_attach_tts(
            note_id="note123",
            week_year="2024-W01",
            year=2024,
            week=1,
            note_title="Summary of week 2024-W01",
        )

        assert result is None

    @patch("services.weekly_summary.extract_summary_text_for_tts")
    @patch("services.weekly_summary.get_note_content")
    @patch("services.weekly_summary.expand_path")
    @patch("services.weekly_summary.config")
    def test_returns_note_info_when_text_too_short(
        self, mock_config, mock_expand_path, mock_get_content, mock_extract_text
    ):
        """Should return note info when text is too short for TTS."""
        from services.weekly_summary import _generate_and_attach_tts

        mock_config.tts_enabled = True
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.get_weekly_summary_audio_path.return_value = "/tmp/2024-W01.mp3"

        mock_path = Mock()
        mock_path.exists.return_value = False
        mock_expand_path.return_value = mock_path

        mock_get_content.return_value = "<p>Short</p>"
        mock_extract_text.return_value = "Too short"  # Less than 50 chars

        result = _generate_and_attach_tts(
            note_id="note123",
            week_year="2024-W01",
            year=2024,
            week=1,
            note_title="Summary of week 2024-W01",
        )

        assert result is not None
        assert result["noteId"] == "note123"

    @patch("services.weekly_summary.generate_audio")
    @patch("services.weekly_summary.extract_summary_text_for_tts")
    @patch("services.weekly_summary.get_note_content")
    @patch("services.weekly_summary.expand_path")
    @patch("services.weekly_summary.config")
    def test_returns_note_info_on_audio_generation_failure(
        self,
        mock_config,
        mock_expand_path,
        mock_get_content,
        mock_extract_text,
        mock_generate_audio,
    ):
        """Should return note info when audio generation fails."""
        from services.weekly_summary import _generate_and_attach_tts

        mock_config.tts_enabled = True
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.elevenlabs_voice_id = "voice123"
        mock_config.elevenlabs_api_key = "key123"
        mock_config.get_weekly_summary_audio_path.return_value = "/tmp/2024-W01.mp3"

        mock_path = Mock()
        mock_path.exists.return_value = False
        mock_expand_path.return_value = mock_path

        mock_get_content.return_value = "<p>Summary content here</p>"
        mock_extract_text.return_value = "Summary content here" * 10  # Long enough
        mock_generate_audio.side_effect = Exception("TTS API error")

        result = _generate_and_attach_tts(
            note_id="note123",
            week_year="2024-W01",
            year=2024,
            week=1,
            note_title="Summary of week 2024-W01",
        )

        assert result is not None
        assert result["noteId"] == "note123"

    @patch("services.weekly_summary.get_audio_duration")
    @patch("services.weekly_summary.expand_path")
    @patch("services.weekly_summary.config")
    def test_handles_zero_duration(
        self, mock_config, mock_expand_path, mock_get_duration
    ):
        """Should handle audio files with zero or None duration."""
        from services.weekly_summary import _generate_and_attach_tts

        mock_config.tts_enabled = True
        mock_config.trilium_url = "http://localhost:8080"
        mock_config.get_weekly_summary_audio_path.return_value = "/tmp/2024-W01.mp3"

        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_expand_path.return_value = mock_path

        mock_get_duration.return_value = None  # Cannot get duration

        with patch(
            "services.weekly_summary._check_audio_already_attached", return_value=True
        ):
            with patch("services.weekly_summary.save_weekly_summary") as mock_save:
                result = _generate_and_attach_tts(
                    note_id="note123",
                    week_year="2024-W01",
                    year=2024,
                    week=1,
                    note_title="Summary of week 2024-W01",
                )

                assert result is not None
                # Check that duration was set to 0
                call_args = mock_save.call_args[1]
                assert call_args["duration_seconds"] == 0


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
        mock_config.weekly_summary_provider = "openai"
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

    @patch("services.weekly_summary.config")
    @patch("services.weekly_summary.get_summary_by_week_year")
    def test_handles_invalid_summary_provider(
        self, mock_get_existing_summary, mock_config
    ):
        """Should return None when invalid summary provider is configured."""
        mock_config.weekly_summary_provider = "invalid_provider"
        mock_get_existing_summary.return_value = None

        with patch(
            "services.weekly_summary.get_books_from_trilium_last_week",
            return_value=[{"video_id": "vid1", "title": "Book 1"}],
        ):
            with patch(
                "services.weekly_summary.fetch_book_summaries",
                return_value=[
                    {
                        "video_id": "vid1",
                        "title": "Book 1",
                        "summary": "Summary",
                        "note_url": "url",
                    }
                ],
            ):
                result = generate_and_save_weekly_summary()

        assert result is None

    @patch("services.weekly_summary.save_weekly_summary")
    @patch("services.weekly_summary.create_weekly_summary_note")
    @patch("services.weekly_summary.generate_weekly_summary_gemini")
    @patch("services.weekly_summary.fetch_book_summaries")
    @patch("services.weekly_summary.get_books_from_trilium_last_week")
    @patch("services.weekly_summary.get_summary_by_week_year")
    @patch("services.weekly_summary.config")
    def test_handles_gemini_summary_failure(
        self,
        mock_config,
        mock_get_existing_summary,
        mock_get_books,
        mock_fetch_summaries,
        mock_generate_summary,
        mock_create_note,
        mock_save_summary,
    ):
        """Should return None when Gemini summary generation fails."""
        mock_config.weekly_summary_provider = "gemini"
        mock_config.tts_enabled = False
        mock_get_existing_summary.return_value = None

        mock_get_books.return_value = [{"video_id": "vid1", "title": "Book 1"}]
        mock_fetch_summaries.return_value = [
            {
                "video_id": "vid1",
                "title": "Book 1",
                "summary": "Summary",
                "note_url": "url",
            }
        ]
        mock_generate_summary.return_value = None  # Gemini fails

        result = generate_and_save_weekly_summary()

        assert result is None
        mock_create_note.assert_not_called()

    @patch("services.weekly_summary.save_weekly_summary")
    @patch("services.weekly_summary.create_weekly_summary_note")
    @patch("services.weekly_summary.generate_weekly_summary_openai")
    @patch("services.weekly_summary.fetch_book_summaries")
    @patch("services.weekly_summary.get_books_from_trilium_last_week")
    @patch("services.weekly_summary.get_summary_by_week_year")
    @patch("services.weekly_summary.config")
    def test_handles_note_creation_failure(
        self,
        mock_config,
        mock_get_existing_summary,
        mock_get_books,
        mock_fetch_summaries,
        mock_generate_summary,
        mock_create_note,
        mock_save_summary,
    ):
        """Should return None when Trilium note creation fails."""
        mock_config.weekly_summary_provider = "openai"
        mock_config.tts_enabled = False
        mock_get_existing_summary.return_value = None

        mock_get_books.return_value = [{"video_id": "vid1", "title": "Book 1"}]
        mock_fetch_summaries.return_value = [
            {
                "video_id": "vid1",
                "title": "Book 1",
                "summary": "Summary",
                "note_url": "url",
            }
        ]
        mock_generate_summary.return_value = "## Overview\nWeekly summary"
        mock_create_note.return_value = None  # Note creation fails

        result = generate_and_save_weekly_summary()

        assert result is None
        mock_save_summary.assert_not_called()

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
        mock_config.weekly_summary_provider = "openai"
        mock_config.tts_enabled = False

        # Mock existing summary in database with a note ID that doesn't exist
        mock_get_existing_summary.return_value = WeeklySummary(
            id=1,
            week_year="2026-W05",
            year=2026,
            week=5,
            title="Old summary",
            trilium_note_id="missing-note-id",
            audio_file_path=None,
            duration_seconds=None,
            created_at="2024-01-01T00:00:00",
        )

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

    @patch("services.weekly_summary.get_summary_by_week_year")
    def test_handles_unexpected_exception(self, mock_get_existing_summary):
        """Should return None on unexpected exception."""
        mock_get_existing_summary.side_effect = Exception("Unexpected error")

        result = generate_and_save_weekly_summary()

        assert result is None

    @patch("services.weekly_summary._generate_and_attach_tts")
    @patch("services.weekly_summary._verify_trilium_note_exists")
    @patch("services.weekly_summary.get_summary_by_week_year")
    @patch("services.weekly_summary.config")
    def test_handles_existing_summary_with_tts(
        self,
        mock_config,
        mock_get_existing_summary,
        mock_verify_note,
        mock_generate_tts,
    ):
        """Should call TTS generation for existing summary."""
        mock_config.tts_enabled = True

        mock_get_existing_summary.return_value = WeeklySummary(
            id=1,
            week_year="2026-W05",
            year=2026,
            week=5,
            title="Summary of week 2026-W05",
            trilium_note_id="note123",
            audio_file_path=None,
            duration_seconds=None,
            created_at="2024-01-01T00:00:00",
        )

        mock_verify_note.return_value = True
        mock_generate_tts.return_value = {"noteId": "note123", "url": "url"}

        result = generate_and_save_weekly_summary()

        assert result is not None
        assert result["noteId"] == "note123"
        mock_generate_tts.assert_called_once()
