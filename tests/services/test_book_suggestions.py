"""Tests for book suggestions service."""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from services.book_suggestions import (
    get_recent_books_from_trilium,
    generate_suggestions_openai,
    generate_suggestions_gemini,
    parse_suggestions,
    filter_already_played,
    get_audiobook_suggestions,
)


@pytest.fixture
def mock_config():
    """Mock configuration."""
    config = Mock()
    config.trilium_url = "http://localhost:8080"
    config.trilium_etapi_token = "test_token"
    config.trilium_parent_note_id = "parent123"
    config.book_suggestions_enabled = True
    config.books_to_analyze = 10
    config.suggestions_count = 4
    config.suggestions_ai_provider = "openai"
    config.openai_api_key = "sk-test"
    config.gemini_api_key = None
    return config


@pytest.mark.asyncio
class TestGetRecentBooksFromTrilium:
    """Tests for fetching books from Trilium."""

    @patch("services.book_suggestions.httpx.AsyncClient")
    @patch("services.book_suggestions.config")
    async def test_fetch_books_success(self, mock_config_module, mock_client_class, mock_config):
        """Test successful audiobook fetching using search API."""
        mock_config_module.trilium_url = mock_config.trilium_url
        mock_config_module.trilium_etapi_token = mock_config.trilium_etapi_token
        mock_config_module.trilium_parent_note_id = mock_config.trilium_parent_note_id

        # Mock search response with Trilium format: {"results": [...]}
        mock_search_response = Mock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {
            "results": [
                {
                    "noteId": "note1",
                    "title": "Atomic Habits - Audiobook Summary",
                    "type": "text",
                    "utcDateModified": "2024-01-15T10:00:00Z",
                },
                {
                    "noteId": "note2",
                    "title": "Deep Work - Audiobook Summary",
                    "type": "text",
                    "utcDateModified": "2024-01-10T10:00:00Z",
                },
            ]
        }

        # Setup mock client
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_search_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        # Call function
        books = await get_recent_books_from_trilium(5)

        # Verify
        assert len(books) == 2
        assert books[0]["title"] == "Atomic Habits - Audiobook Summary"
        assert books[1]["title"] == "Deep Work - Audiobook Summary"
        # Verify sorted by most recent first
        assert books[0]["dateModified"] > books[1]["dateModified"]

    @patch("services.book_suggestions.httpx.AsyncClient")
    @patch("services.book_suggestions.config")
    async def test_fetch_books_empty(self, mock_config_module, mock_client_class, mock_config):
        """Test when no children found in parent note."""
        mock_config_module.trilium_url = mock_config.trilium_url
        mock_config_module.trilium_etapi_token = mock_config.trilium_etapi_token
        mock_config_module.trilium_parent_note_id = mock_config.trilium_parent_note_id

        # Mock empty search response in Trilium format
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        books = await get_recent_books_from_trilium(5)

        assert len(books) == 0

    @patch("services.book_suggestions.httpx.AsyncClient")
    @patch("services.book_suggestions.config")
    async def test_fetch_books_error(self, mock_config_module, mock_client_class, mock_config):
        """Test error handling."""
        mock_config_module.trilium_url = mock_config.trilium_url
        mock_config_module.trilium_etapi_token = mock_config.trilium_etapi_token
        mock_config_module.trilium_parent_note_id = mock_config.trilium_parent_note_id

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Network error"))
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        books = await get_recent_books_from_trilium(5)

        assert len(books) == 0


class TestGenerateSuggestionsOpenAI:
    """Tests for OpenAI suggestion generation."""

    @patch("services.book_suggestions.search_youtube_audiobook")
    @patch("services.book_suggestions.OpenAI")
    @patch("services.book_suggestions.config")
    def test_generate_suggestions_success(
        self, mock_config_module, mock_openai_class, mock_search, mock_config
    ):
        """Test successful suggestion generation."""
        mock_config_module.openai_api_key = mock_config.openai_api_key

        # Mock OpenAI response (new format without URLs)
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = """
TITLE: Atomic Habits
AUTHOR: James Clear
---
TITLE: Deep Work
AUTHOR: Cal Newport
---
"""

        mock_client = Mock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        # Mock YouTube search to return video IDs
        mock_search.side_effect = ["dQw4w9WgXcQ", "jNQXAC9IVRw"]

        suggestions = generate_suggestions_openai(["Book One", "Book Two"], 2)

        assert len(suggestions) == 2
        assert suggestions[0]["title"] == "Atomic Habits"
        assert suggestions[0]["author"] == "James Clear"
        assert suggestions[0]["video_id"] == "dQw4w9WgXcQ"
        assert mock_search.call_count == 2

    @patch("services.book_suggestions.OpenAI")
    @patch("services.book_suggestions.config")
    def test_generate_suggestions_error(self, mock_config_module, mock_openai_class, mock_config):
        """Test error handling in OpenAI generation."""
        mock_config_module.openai_api_key = mock_config.openai_api_key

        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = Exception("API error")
        mock_openai_class.return_value = mock_client

        suggestions = generate_suggestions_openai(["Book One"], 1)

        assert len(suggestions) == 0


class TestGenerateSuggestionsGemini:
    """Tests for Gemini suggestion generation."""

    @pytest.mark.skip(reason="Gemini library not always available in test environment")
    @patch("google.generativeai.GenerativeModel")
    @patch("google.generativeai.configure")
    @patch("services.book_suggestions.config")
    def test_generate_suggestions_success(
        self, mock_config_module, mock_configure, mock_model_class, mock_config
    ):
        """Test successful Gemini suggestion generation."""
        mock_config_module.gemini_api_key = mock_config.gemini_api_key

        # Mock Gemini response
        mock_response = Mock()
        mock_response.text = """
TITLE: Can't Hurt Me
AUTHOR: David Goggins
URL: https://www.youtube.com/watch?v=BvWB7B8tXD8
---
"""

        mock_model = Mock()
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        suggestions = generate_suggestions_gemini(["Book One"], 1)

        assert len(suggestions) == 1
        assert suggestions[0]["title"] == "Can't Hurt Me"
        assert suggestions[0]["author"] == "David Goggins"
        assert suggestions[0]["video_id"] == "BvWB7B8tXD8"

    @pytest.mark.skip(reason="Gemini library not always available in test environment")
    @patch("google.generativeai.configure")
    @patch("services.book_suggestions.config")
    def test_generate_suggestions_import_error(
        self, mock_config_module, mock_configure, mock_config
    ):
        """Test handling when Gemini library has error."""
        mock_config_module.gemini_api_key = mock_config.gemini_api_key

        mock_configure.side_effect = Exception("API error")

        suggestions = generate_suggestions_gemini(["Book One"], 1)

        assert len(suggestions) == 0


class TestSearchYoutubeAudiobook:
    """Tests for YouTube audiobook search."""

    @patch("subprocess.run")
    def test_search_success(self, mock_run):
        """Test successful YouTube search."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = (
            '{"id": "abc123", "title": "Atomic Habits Audiobook", "duration": 3600}\n'
        )
        mock_run.return_value = mock_result

        from services.book_suggestions import search_youtube_audiobook

        video_id = search_youtube_audiobook("Atomic Habits", "James Clear")

        assert video_id == "abc123"

    @patch("subprocess.run")
    def test_search_short_video_filtered(self, mock_run):
        """Test that short videos are filtered out."""
        mock_result = Mock()
        mock_result.returncode = 0
        # Video is only 10 minutes (600 seconds) - too short for full audiobook
        mock_result.stdout = (
            '{"id": "short1", "title": "Atomic Habits Audiobook Summary", "duration": 600}\n'
        )
        mock_run.return_value = mock_result

        from services.book_suggestions import search_youtube_audiobook

        video_id = search_youtube_audiobook("Atomic Habits", "James Clear")

        assert video_id is None

    @patch("subprocess.run")
    def test_search_no_audiobook_keyword(self, mock_run):
        """Test that videos without 'audiobook' in title are filtered."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = (
            '{"id": "review1", "title": "Atomic Habits Review", "duration": 3600}\n'
        )
        mock_run.return_value = mock_result

        from services.book_suggestions import search_youtube_audiobook

        video_id = search_youtube_audiobook("Atomic Habits", "James Clear")

        assert video_id is None

    @patch("subprocess.run")
    def test_search_error(self, mock_run):
        """Test error handling in YouTube search."""
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "Search failed"
        mock_run.return_value = mock_result

        from services.book_suggestions import search_youtube_audiobook

        video_id = search_youtube_audiobook("Unknown Book", "Unknown Author")

        assert video_id is None


class TestParseSuggestions:
    """Tests for parsing AI responses."""

    @patch("services.book_suggestions.search_youtube_audiobook")
    def test_parse_valid_suggestions(self, mock_search):
        """Test parsing well-formed suggestions."""
        content = """
TITLE: Atomic Habits
AUTHOR: James Clear
---
TITLE: Deep Work
AUTHOR: Cal Newport
---
"""
        # Mock YouTube search to return video IDs
        mock_search.side_effect = ["dQw4w9WgXcQ", "jNQXAC9IVRw"]

        suggestions = parse_suggestions(content)

        assert len(suggestions) == 2
        assert suggestions[0]["title"] == "Atomic Habits"
        assert suggestions[0]["video_id"] == "dQw4w9WgXcQ"
        assert suggestions[1]["video_id"] == "jNQXAC9IVRw"
        assert mock_search.call_count == 2

    @patch("services.book_suggestions.search_youtube_audiobook")
    def test_parse_missing_fields(self, mock_search):
        """Test parsing with missing required fields."""
        content = """
TITLE: Incomplete Book
---
AUTHOR: No Title
---
TITLE: Valid Book
AUTHOR: Valid Author
---
"""
        # Mock YouTube search - only called for valid entries
        mock_search.return_value = "dQw4w9WgXcQ"

        suggestions = parse_suggestions(content)

        # Only the valid one should be included
        assert len(suggestions) == 1
        assert suggestions[0]["title"] == "Valid Book"
        assert mock_search.call_count == 1

    @patch("services.book_suggestions.search_youtube_audiobook")
    def test_parse_empty_content(self, mock_search):
        """Test parsing empty content."""
        suggestions = parse_suggestions("")

        assert len(suggestions) == 0
        assert mock_search.call_count == 0


@pytest.mark.asyncio
class TestFilterAlreadyPlayed:
    """Tests for filtering played audiobooks."""

    @patch("services.database.get_history")
    async def test_filter_played(self, mock_get_history):
        """Test filtering out already played videos."""
        mock_get_history.return_value = [
            {"youtube_id": "abc123", "title": "Played Video 1"},
            {"youtube_id": "def456", "title": "Played Video 2"},
        ]

        suggestions = [
            {"video_id": "abc123", "title": "Already Played"},
            {"video_id": "xyz789", "title": "New Video"},
            {"video_id": "uvw012", "title": "Another New Video"},
        ]

        filtered = await filter_already_played(suggestions)

        assert len(filtered) == 2
        assert filtered[0]["video_id"] == "xyz789"
        assert filtered[1]["video_id"] == "uvw012"

    @patch("services.database.get_history")
    async def test_filter_all_played(self, mock_get_history):
        """Test when all suggestions already played."""
        mock_get_history.return_value = [
            {"youtube_id": "abc123", "title": "Video 1"},
            {"youtube_id": "def456", "title": "Video 2"},
        ]

        suggestions = [
            {"video_id": "abc123", "title": "Video 1"},
            {"video_id": "def456", "title": "Video 2"},
        ]

        filtered = await filter_already_played(suggestions)

        assert len(filtered) == 0

    @patch("services.database.get_history")
    async def test_filter_error_handling(self, mock_get_history):
        """Test error handling in filter."""
        mock_get_history.side_effect = Exception("Database error")

        suggestions = [{"video_id": "xyz789", "title": "Video"}]

        # Should return unfiltered on error
        filtered = await filter_already_played(suggestions)

        assert len(filtered) == 1


@pytest.mark.asyncio
class TestGetAudiobookSuggestions:
    """Tests for main suggestion workflow."""

    @patch("services.book_suggestions.filter_already_played")
    @patch("services.book_suggestions.generate_suggestions_openai")
    @patch("services.book_suggestions.get_recent_books_from_trilium")
    @patch("services.book_suggestions.config")
    async def test_full_workflow_success(
        self, mock_config_module, mock_get_books, mock_generate, mock_filter, mock_config
    ):
        """Test complete suggestion workflow."""
        mock_config_module.book_suggestions_enabled = True
        mock_config_module.books_to_analyze = 10
        mock_config_module.suggestions_count = 4
        mock_config_module.suggestions_ai_provider = "openai"

        # Mock books
        mock_get_books.return_value = [
            {"title": "Book 1", "noteId": "n1"},
            {"title": "Book 2", "noteId": "n2"},
        ]

        # Mock suggestions
        mock_suggestions = [
            {"title": "Suggestion 1", "video_id": "vid1", "youtube_url": "url1"},
            {"title": "Suggestion 2", "video_id": "vid2", "youtube_url": "url2"},
        ]
        mock_generate.return_value = mock_suggestions

        # Mock filter (no filtering)
        mock_filter.return_value = mock_suggestions

        # Call function
        result = await get_audiobook_suggestions()

        # Verify
        assert len(result) == 2
        assert result[0]["title"] == "Suggestion 1"
        mock_get_books.assert_called_once()
        mock_generate.assert_called_once()

    @patch("services.book_suggestions.config")
    async def test_disabled_feature(self, mock_config_module, mock_config):
        """Test when feature is disabled."""
        mock_config_module.book_suggestions_enabled = False

        result = await get_audiobook_suggestions()

        assert len(result) == 0

    @patch("services.book_suggestions.get_recent_books_from_trilium")
    @patch("services.book_suggestions.config")
    async def test_no_books_found(self, mock_config_module, mock_get_books, mock_config):
        """Test when no books found in Trilium."""
        mock_config_module.book_suggestions_enabled = True
        mock_get_books.return_value = []

        result = await get_audiobook_suggestions()

        assert len(result) == 0
