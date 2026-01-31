"""Tests for book suggestions service."""

import pytest
from unittest.mock import Mock, patch
from services.book_suggestions import (
    filter_already_played,
    generate_theme_gemini,
    generate_theme_openai,
    get_recent_summaries,
    get_video_suggestions,
    search_youtube_by_theme,
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
class TestGetRecentSummaries:
    """Tests for fetching recent summaries."""

    @patch("services.trilium.get_note_content")
    @patch("services.trilium.check_video_exists")
    @patch("services.book_suggestions.get_history")
    async def test_fetch_summaries_success(
        self, mock_get_history, mock_check_video, mock_get_content
    ):
        """Test successful summary fetching from history and Trilium."""
        # Mock history from database
        mock_get_history.return_value = [
            {"youtube_id": "vid1", "title": "Video 1"},
            {"youtube_id": "vid2", "title": "Video 2"},
        ]

        # Mock Trilium note existence and content
        mock_check_video.side_effect = [
            {"noteId": "note1"},
            {"noteId": "note2"},
        ]
        mock_get_content.side_effect = [
            "<h3>Summary</h3><p>This is the summary for video 1.</p>",
            "<h3>Summary</h3><p>This is the summary for video 2.</p>",
        ]

        # Call function
        summaries = await get_recent_summaries(5)

        # Verify
        assert len(summaries) == 2
        assert summaries[0]["video_id"] == "vid1"
        assert summaries[0]["title"] == "Video 1"
        assert "summary for video 1" in summaries[0]["summary"]

    @patch("services.book_suggestions.get_history")
    async def test_get_recent_summaries_empty(self, mock_get_history):
        """Test when no history found."""
        mock_get_history.return_value = []

        summaries = await get_recent_summaries(5)

        assert len(summaries) == 0

    @patch("services.book_suggestions.get_history")
    async def test_fetch_summaries_error(self, mock_get_history):
        """Test error handling."""
        mock_get_history.side_effect = Exception("Database error")

        summaries = await get_recent_summaries(5)

        assert len(summaries) == 0


class TestGenerateThemeOpenAI:
    """Tests for OpenAI theme generation."""

    @patch("services.book_suggestions.OpenAI")
    @patch("services.book_suggestions.config")
    def test_generate_theme_success(
        self, mock_config_module, mock_openai_class, mock_config
    ):
        """Test successful theme generation."""
        mock_config_module.openai_api_key = mock_config.openai_api_key

        # Mock OpenAI response - returns a single theme sentence
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[
            0
        ].message.content = (
            "Personal development and productivity improvement strategies"
        )

        mock_client = Mock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        summaries = [
            {"summary": "Summary about atomic habits"},
            {"summary": "Summary about deep work"},
        ]
        theme = generate_theme_openai(summaries)

        assert theme == "Personal development and productivity improvement strategies"
        assert mock_client.chat.completions.create.called

    @patch("services.book_suggestions.OpenAI")
    @patch("services.book_suggestions.config")
    def test_generate_theme_error(
        self, mock_config_module, mock_openai_class, mock_config
    ):
        """Test error handling in OpenAI theme generation."""
        mock_config_module.openai_api_key = mock_config.openai_api_key

        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = Exception("API error")
        mock_openai_class.return_value = mock_client

        summaries = [{"summary": "Book summary"}]
        theme = generate_theme_openai(summaries)

        assert theme is None


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

        suggestions = generate_theme_gemini(["Book One"], 1)

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

        suggestions = generate_theme_gemini(["Book One"], 1)

        assert len(suggestions) == 0


class TestSearchYoutubeByTheme:
    """Tests for YouTube theme-based search."""

    @patch("subprocess.run")
    def test_search_success(self, mock_run):
        """Test successful YouTube search."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = '{"id": "abc123", "title": "Atomic Habits Audiobook", "duration": 3600, "uploader": "Channel"}\n'
        mock_run.return_value = mock_result

        videos = search_youtube_by_theme("Atomic Habits", 1)

        assert len(videos) == 1
        assert videos[0]["video_id"] == "abc123"
        assert videos[0]["title"] == "Atomic Habits Audiobook"

    @patch("subprocess.run")
    def test_search_short_video_filtered(self, mock_run):
        """Test that short videos (< 10 minutes) are filtered out."""
        mock_result = Mock()
        mock_result.returncode = 0
        # Video is only 5 minutes (300 seconds) - too short
        mock_result.stdout = '{"id": "short1", "title": "Atomic Habits Summary", "duration": 300, "uploader": "Channel"}\n'
        mock_run.return_value = mock_result

        videos = search_youtube_by_theme("Atomic Habits", 1)

        assert len(videos) == 0

    @patch("subprocess.run")
    def test_search_filters_short_keeps_long(self, mock_run):
        """Test that search filters short videos but keeps long ones."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = (
            '{"id": "short1", "title": "Short Video", "duration": 300, "uploader": "Channel"}\n'
            '{"id": "long1", "title": "Long Video", "duration": 3600, "uploader": "Channel"}\n'
        )
        mock_run.return_value = mock_result

        videos = search_youtube_by_theme("test theme", 1)

        assert len(videos) == 1
        assert videos[0]["video_id"] == "long1"

    @patch("subprocess.run")
    def test_search_error(self, mock_run):
        """Test error handling in YouTube search."""
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "Search failed"
        mock_run.return_value = mock_result

        videos = search_youtube_by_theme("test theme", 1)

        assert len(videos) == 0


@pytest.mark.asyncio
class TestFilterAlreadyPlayed:
    """Tests for filtering played audiobooks."""

    @patch("services.book_suggestions.get_history")
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

    @patch("services.book_suggestions.get_history")
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

    @patch("services.book_suggestions.get_history")
    async def test_filter_error_handling(self, mock_get_history):
        """Test error handling in filter."""
        mock_get_history.side_effect = Exception("Database error")

        suggestions = [{"video_id": "xyz789", "title": "Video"}]

        # Should return unfiltered on error
        filtered = await filter_already_played(suggestions)

        assert len(filtered) == 1


@pytest.mark.asyncio
class TestGetVideoSuggestions:
    """Tests for main suggestion workflow."""

    @patch("services.book_suggestions.filter_already_played")
    @patch("services.book_suggestions.search_youtube_by_theme")
    @patch("services.book_suggestions.generate_theme_openai")
    @patch("services.book_suggestions.get_recent_summaries")
    @patch("services.book_suggestions.config")
    async def test_full_workflow_success(
        self,
        mock_config_module,
        mock_get_summaries,
        mock_generate_theme,
        mock_search,
        mock_filter,
        mock_config,
    ):
        """Test complete suggestion workflow."""
        mock_config_module.book_suggestions_enabled = True
        mock_config_module.books_to_analyze = 10
        mock_config_module.suggestions_count = 4
        mock_config_module.suggestions_ai_provider = "openai"

        # Mock summaries
        mock_get_summaries.return_value = [
            {"video_id": "v1", "title": "Video 1", "summary": "Summary 1"},
            {"video_id": "v2", "title": "Video 2", "summary": "Summary 2"},
        ]

        # Mock theme generation
        mock_generate_theme.return_value = "Personal development and productivity"

        # Mock YouTube search results
        mock_videos = [
            {"video_id": "vid1", "title": "Suggestion 1", "youtube_url": "url1"},
            {"video_id": "vid2", "title": "Suggestion 2", "youtube_url": "url2"},
        ]
        mock_search.return_value = mock_videos

        # Mock filter (no filtering)
        mock_filter.return_value = mock_videos

        # Call function
        result = await get_video_suggestions()

        # Verify
        assert len(result) == 2
        assert result[0]["title"] == "Suggestion 1"
        mock_get_summaries.assert_called_once()
        mock_generate_theme.assert_called_once()
        mock_search.assert_called_once()

    @patch("services.book_suggestions.config")
    async def test_disabled_feature(self, mock_config_module, mock_config):
        """Test when feature is disabled."""
        mock_config_module.book_suggestions_enabled = False

        result = await get_video_suggestions()

        assert len(result) == 0

    @patch("services.book_suggestions.get_recent_summaries")
    @patch("services.book_suggestions.config")
    async def test_no_summaries_found(
        self, mock_config_module, mock_get_summaries, mock_config
    ):
        """Test when no summaries found."""
        mock_config_module.book_suggestions_enabled = True
        mock_get_summaries.return_value = []

        result = await get_video_suggestions()

        assert len(result) == 0
