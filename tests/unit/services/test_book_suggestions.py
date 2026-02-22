"""Tests for book suggestions service."""

import pytest
import subprocess
from unittest.mock import Mock, patch
from services.book_suggestions import (
    _extract_text_from_html,
    _fetch_summary_for_video,
    _parse_video_json_line,
    filter_already_played,
    generate_theme_gemini,
    generate_theme_openai,
    get_recent_summaries,
    get_video_suggestions,
    search_youtube_by_theme,
)
from services.models import PlayHistoryItem, VideoSummary


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


class TestExtractTextFromHtml:
    """Tests for HTML text extraction."""

    def test_extract_text_basic(self):
        """Test basic HTML extraction."""
        html = "<h3>Summary</h3><p>This is some text.</p>"
        text = _extract_text_from_html(html)
        assert "Summary" in text
        assert "This is some text" in text

    def test_extract_text_removes_youtube_link(self):
        """Test that YouTube link section is removed."""
        html = """<p>Summary content</p>
        <p style="margin-top: 2em;">
            <strong>YouTube:</strong> <a href="https://youtube.com">Link</a>
        </p>"""
        text = _extract_text_from_html(html)
        assert "Summary content" in text
        assert "YouTube" not in text
        assert "Link" not in text

    def test_extract_text_whitespace_cleanup(self):
        """Test whitespace is properly cleaned."""
        html = "<p>Text   with    lots     of      spaces</p>"
        text = _extract_text_from_html(html)
        assert "Text with lots of spaces" in text


class TestParseVideoJsonLine:
    """Tests for JSON line parsing."""

    def test_parse_valid_video(self):
        """Test parsing valid video JSON."""
        line = '{"id": "abc123", "title": "Test Video", "uploader": "Channel", "duration": 3600}'
        result = _parse_video_json_line(line)

        assert result is not None
        assert result["video_id"] == "abc123"
        assert result["title"] == "Test Video"
        assert result["channel"] == "Channel"
        assert result["duration"] == 3600

    def test_parse_empty_line(self):
        """Test parsing empty line."""
        result = _parse_video_json_line("")
        assert result is None

    def test_parse_invalid_json(self):
        """Test parsing invalid JSON."""
        line = "not a valid json"
        result = _parse_video_json_line(line)
        assert result is None

    def test_parse_short_video_filtered(self):
        """Test that videos shorter than 10 minutes are filtered."""
        line = '{"id": "short", "title": "Short Video", "duration": 300, "uploader": "Channel"}'
        result = _parse_video_json_line(line)
        assert result is None  # Should be filtered out

    def test_parse_long_video_accepted(self):
        """Test that videos longer than 10 minutes are accepted."""
        line = '{"id": "long", "title": "Long Video", "duration": 3600, "uploader": "Channel"}'
        result = _parse_video_json_line(line)
        assert result is not None
        assert result["video_id"] == "long"


class TestFetchSummaryForVideo:
    """Tests for fetching summary from Trilium."""

    @patch("services.trilium.get_note_content")
    @patch("services.trilium.check_video_exists")
    def test_fetch_summary_success(self, mock_check, mock_get_content):
        """Test successful summary fetch."""
        item = PlayHistoryItem(
            id=1,
            youtube_id="vid1",
            title="Test Video",
            channel=None,
            thumbnail_url=None,
            play_count=1,
            created_at="2024-01-01T00:00:00",
            last_played_at="2024-01-01T00:00:00",
        )

        mock_check.return_value = {"noteId": "note123", "url": "http://trilium/note123"}
        mock_get_content.return_value = "<h3>Summary</h3><p>Test summary content</p>"

        result = _fetch_summary_for_video(item)

        assert result is not None
        assert result.video_id == "vid1"
        assert result.title == "Test Video"
        assert "Test summary content" in result.summary
        assert result.note_url == "http://trilium/note123"

    @patch("services.trilium.check_video_exists")
    def test_fetch_summary_no_note(self, mock_check):
        """Test when no Trilium note exists."""
        item = PlayHistoryItem(
            id=1,
            youtube_id="vid1",
            title="Test Video",
            channel=None,
            thumbnail_url=None,
            play_count=1,
            created_at="2024-01-01T00:00:00",
            last_played_at="2024-01-01T00:00:00",
        )

        mock_check.return_value = None

        result = _fetch_summary_for_video(item)
        assert result is None

    @patch("services.trilium.get_note_content")
    @patch("services.trilium.check_video_exists")
    def test_fetch_summary_no_content(self, mock_check, mock_get_content):
        """Test when note content fetch fails."""
        item = PlayHistoryItem(
            id=1,
            youtube_id="vid1",
            title="Test Video",
            channel=None,
            thumbnail_url=None,
            play_count=1,
            created_at="2024-01-01T00:00:00",
            last_played_at="2024-01-01T00:00:00",
        )

        mock_check.return_value = {"noteId": "note123"}
        mock_get_content.return_value = None

        result = _fetch_summary_for_video(item)
        assert result is None

    @patch("services.trilium.get_note_content")
    @patch("services.trilium.check_video_exists")
    def test_fetch_summary_empty_text(self, mock_check, mock_get_content):
        """Test when HTML extraction yields empty text."""
        item = PlayHistoryItem(
            id=1,
            youtube_id="vid1",
            title="Test Video",
            channel=None,
            thumbnail_url=None,
            play_count=1,
            created_at="2024-01-01T00:00:00",
            last_played_at="2024-01-01T00:00:00",
        )

        mock_check.return_value = {"noteId": "note123"}
        mock_get_content.return_value = "<div></div>"  # Empty content

        result = _fetch_summary_for_video(item)
        assert result is None


class TestGetRecentSummaries:
    """Tests for fetching recent summaries."""

    @patch("services.trilium.get_note_content")
    @patch("services.trilium.check_video_exists")
    @patch("services.book_suggestions.get_history")
    def test_fetch_summaries_success(
        self, mock_get_history, mock_check_video, mock_get_content
    ):
        """Test successful summary fetching from history and Trilium."""
        # Mock history from database
        mock_get_history.return_value = [
            PlayHistoryItem(
                id=1,
                youtube_id="vid1",
                title="Video 1",
                channel=None,
                thumbnail_url=None,
                play_count=1,
                created_at="2024-01-01T00:00:00",
                last_played_at="2024-01-01T00:00:00",
            ),
            PlayHistoryItem(
                id=2,
                youtube_id="vid2",
                title="Video 2",
                channel=None,
                thumbnail_url=None,
                play_count=1,
                created_at="2024-01-01T00:00:00",
                last_played_at="2024-01-01T00:00:00",
            ),
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
        summaries = get_recent_summaries(5)

        # Verify
        assert len(summaries) == 2
        assert summaries[0].video_id == "vid1"
        assert summaries[0].title == "Video 1"
        assert "summary for video 1" in summaries[0].summary

    @patch("services.book_suggestions.get_history")
    def test_get_recent_summaries_empty(self, mock_get_history):
        """Test when no history found."""
        mock_get_history.return_value = []

        summaries = get_recent_summaries(5)

        assert len(summaries) == 0

    @patch("services.book_suggestions.get_history")
    def test_fetch_summaries_error(self, mock_get_history):
        """Test error handling."""
        mock_get_history.side_effect = Exception("Database error")

        summaries = get_recent_summaries(5)

        assert len(summaries) == 0

    @patch("services.trilium.get_note_content")
    @patch("services.trilium.check_video_exists")
    @patch("services.book_suggestions.get_history")
    def test_stops_when_limit_reached(
        self, mock_get_history, mock_check_video, mock_get_content
    ):
        """Test that fetching stops when we have enough summaries."""
        # Mock history with 10 videos
        mock_get_history.return_value = [
            PlayHistoryItem(
                id=i,
                youtube_id=f"vid{i}",
                title=f"Video {i}",
                channel=None,
                thumbnail_url=None,
                play_count=1,
                created_at="2024-01-01T00:00:00",
                last_played_at="2024-01-01T00:00:00",
            )
            for i in range(10)
        ]

        # All videos have notes and content
        mock_check_video.return_value = {"noteId": "note123"}
        mock_get_content.return_value = "<h3>Summary</h3><p>Test content</p>"

        # Request only 3 summaries
        summaries = get_recent_summaries(3)

        # Should stop after 3 summaries
        assert len(summaries) == 3
        # check_video_exists should only be called 3 times, not 10
        assert mock_check_video.call_count == 3


class TestGenerateThemeOpenAI:
    """Tests for OpenAI theme generation."""

    @patch("services.book_suggestions.get_tracked_openai_client")
    def test_generate_theme_success(self, mock_get_client):
        """Test successful theme generation."""
        # Mock OpenAI response - returns a single theme sentence
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[
            0
        ].message.content = (
            "Personal development and productivity improvement strategies"
        )

        mock_client = Mock()
        mock_client.create_chat_completion.return_value = mock_response
        mock_get_client.return_value = mock_client

        summaries = [
            VideoSummary(
                video_id="vid1",
                title="Video 1",
                summary="Summary about atomic habits",
            ),
            VideoSummary(
                video_id="vid2",
                title="Video 2",
                summary="Summary about deep work",
            ),
        ]
        theme = generate_theme_openai(summaries)

        assert theme == "Personal development and productivity improvement strategies"
        assert mock_client.create_chat_completion.called

    @patch("services.book_suggestions.get_tracked_openai_client")
    def test_generate_theme_error(self, mock_get_client):
        """Test error handling in OpenAI theme generation."""
        mock_client = Mock()
        mock_client.create_chat_completion.side_effect = Exception("API error")
        mock_get_client.return_value = mock_client

        summaries = [{"summary": "Book summary"}]
        theme = generate_theme_openai(summaries)

        assert theme is None


class TestGenerateThemeGemini:
    """Tests for Gemini theme generation."""

    @patch("services.book_suggestions.get_tracked_gemini_client")
    def test_generate_theme_success(self, mock_get_client):
        """Test successful Gemini theme generation."""
        # Mock Gemini response
        mock_response = Mock()
        mock_response.text = "Personal development and productivity strategies"

        mock_client = Mock()
        mock_client.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        summaries = [
            VideoSummary(
                video_id="vid1",
                title="Video 1",
                summary="Summary about atomic habits",
            ),
            VideoSummary(
                video_id="vid2",
                title="Video 2",
                summary="Summary about deep work",
            ),
        ]

        theme = generate_theme_gemini(summaries)

        assert theme == "Personal development and productivity strategies"
        assert mock_client.generate_content.called

    @patch("services.book_suggestions.get_tracked_gemini_client")
    def test_generate_theme_error(self, mock_get_client):
        """Test error handling in Gemini theme generation."""
        mock_client = Mock()
        mock_client.generate_content.side_effect = Exception("API error")
        mock_get_client.return_value = mock_client

        summaries = [
            VideoSummary(
                video_id="vid1",
                title="Video 1",
                summary="Summary text",
            )
        ]

        theme = generate_theme_gemini(summaries)
        assert theme is None

    @patch("services.book_suggestions.get_tracked_gemini_client")
    def test_generate_theme_empty_response(self, mock_get_client):
        """Test handling of empty response from Gemini."""
        mock_response = Mock()
        mock_response.text = None

        mock_client = Mock()
        mock_client.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        summaries = [
            VideoSummary(
                video_id="vid1",
                title="Video 1",
                summary="Summary text",
            )
        ]

        theme = generate_theme_gemini(summaries)
        assert theme is None


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

    @patch("subprocess.run")
    def test_search_timeout(self, mock_run):
        """Test handling of subprocess timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="yt-dlp", timeout=30)

        videos = search_youtube_by_theme("test theme", 1)

        assert len(videos) == 0

    @patch("subprocess.run")
    def test_search_exception(self, mock_run):
        """Test handling of general exception."""
        mock_run.side_effect = Exception("Unexpected error")

        videos = search_youtube_by_theme("test theme", 1)

        assert len(videos) == 0

    @patch("subprocess.run")
    def test_search_invalid_json_line(self, mock_run):
        """Test handling of invalid JSON in output."""
        mock_result = Mock()
        mock_result.returncode = 0
        # Mix of valid and invalid JSON lines
        mock_result.stdout = (
            '{"id": "valid1", "title": "Valid Video", "duration": 3600, "uploader": "Channel"}\n'
            "invalid json line\n"
            '{"id": "valid2", "title": "Another Video", "duration": 3600, "uploader": "Channel"}\n'
        )
        mock_run.return_value = mock_result

        videos = search_youtube_by_theme("test theme", 2)

        # Should skip invalid line and return only valid ones
        assert len(videos) == 2
        assert videos[0]["video_id"] == "valid1"
        assert videos[1]["video_id"] == "valid2"


class TestFilterAlreadyPlayed:
    """Tests for filtering played audiobooks."""

    @patch("services.book_suggestions.get_history")
    def test_filter_played(self, mock_get_history):
        """Test filtering out already played videos."""
        mock_get_history.return_value = [
            PlayHistoryItem(
                id=1,
                youtube_id="abc123",
                title="Played Video 1",
                channel=None,
                thumbnail_url=None,
                play_count=1,
                created_at="2024-01-01T00:00:00",
                last_played_at="2024-01-01T00:00:00",
            ),
            PlayHistoryItem(
                id=2,
                youtube_id="def456",
                title="Played Video 2",
                channel=None,
                thumbnail_url=None,
                play_count=1,
                created_at="2024-01-01T00:00:00",
                last_played_at="2024-01-01T00:00:00",
            ),
        ]

        suggestions = [
            {"video_id": "abc123", "title": "Already Played"},
            {"video_id": "xyz789", "title": "New Video"},
            {"video_id": "uvw012", "title": "Another New Video"},
        ]

        filtered = filter_already_played(suggestions)

        assert len(filtered) == 2
        assert filtered[0]["video_id"] == "xyz789"
        assert filtered[1]["video_id"] == "uvw012"

    @patch("services.book_suggestions.get_history")
    def test_filter_all_played(self, mock_get_history):
        """Test when all suggestions already played."""
        mock_get_history.return_value = [
            PlayHistoryItem(
                id=1,
                youtube_id="abc123",
                title="Video 1",
                channel=None,
                thumbnail_url=None,
                play_count=1,
                created_at="2024-01-01T00:00:00",
                last_played_at="2024-01-01T00:00:00",
            ),
            PlayHistoryItem(
                id=2,
                youtube_id="def456",
                title="Video 2",
                channel=None,
                thumbnail_url=None,
                play_count=1,
                created_at="2024-01-01T00:00:00",
                last_played_at="2024-01-01T00:00:00",
            ),
        ]

        suggestions = [
            {"video_id": "abc123", "title": "Video 1"},
            {"video_id": "def456", "title": "Video 2"},
        ]

        filtered = filter_already_played(suggestions)

        assert len(filtered) == 0

    @patch("services.book_suggestions.get_history")
    def test_filter_error_handling(self, mock_get_history):
        """Test error handling in filter."""
        mock_get_history.side_effect = Exception("Database error")

        suggestions = [{"video_id": "xyz789", "title": "Video"}]

        # Should return unfiltered on error
        filtered = filter_already_played(suggestions)

        assert len(filtered) == 1


class TestGetVideoSuggestions:
    """Tests for main suggestion workflow."""

    @patch("services.book_suggestions.filter_already_played")
    @patch("services.book_suggestions.search_youtube_by_theme")
    @patch("services.book_suggestions.generate_theme_openai")
    @patch("services.book_suggestions.get_recent_summaries")
    @patch("services.book_suggestions.config")
    def test_full_workflow_success(
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
        result = get_video_suggestions()

        # Verify
        assert len(result) == 2
        assert result[0]["title"] == "Suggestion 1"
        mock_get_summaries.assert_called_once()
        mock_generate_theme.assert_called_once()
        mock_search.assert_called_once()

    @patch("services.book_suggestions.config")
    def test_disabled_feature(self, mock_config_module, mock_config):
        """Test when feature is disabled."""
        mock_config_module.book_suggestions_enabled = False

        result = get_video_suggestions()

        assert len(result) == 0

    @patch("services.book_suggestions.get_recent_summaries")
    @patch("services.book_suggestions.config")
    def test_no_summaries_found(
        self, mock_config_module, mock_get_summaries, mock_config
    ):
        """Test when no summaries found."""
        mock_config_module.book_suggestions_enabled = True
        mock_get_summaries.return_value = []

        result = get_video_suggestions()

        assert len(result) == 0

    @patch("services.book_suggestions.generate_theme_gemini")
    @patch("services.book_suggestions.get_recent_summaries")
    @patch("services.book_suggestions.config")
    def test_gemini_provider(
        self, mock_config_module, mock_get_summaries, mock_generate_gemini, mock_config
    ):
        """Test with Gemini as AI provider."""
        mock_config_module.book_suggestions_enabled = True
        mock_config_module.books_to_analyze = 10
        mock_config_module.suggestions_count = 4
        mock_config_module.suggestions_ai_provider = "gemini"

        mock_get_summaries.return_value = [
            VideoSummary(
                video_id="v1",
                title="Video 1",
                summary="Summary 1",
            )
        ]
        mock_generate_gemini.return_value = None  # Theme generation failed

        result = get_video_suggestions()

        assert len(result) == 0
        mock_generate_gemini.assert_called_once()

    @patch("services.book_suggestions.get_recent_summaries")
    @patch("services.book_suggestions.config")
    def test_invalid_ai_provider(
        self, mock_config_module, mock_get_summaries, mock_config
    ):
        """Test with invalid AI provider."""
        mock_config_module.book_suggestions_enabled = True
        mock_config_module.books_to_analyze = 10
        mock_config_module.suggestions_ai_provider = "invalid_provider"

        mock_get_summaries.return_value = [
            VideoSummary(
                video_id="v1",
                title="Video 1",
                summary="Summary 1",
            )
        ]

        result = get_video_suggestions()

        assert len(result) == 0

    @patch("services.book_suggestions.generate_theme_openai")
    @patch("services.book_suggestions.get_recent_summaries")
    @patch("services.book_suggestions.config")
    def test_theme_generation_fails(
        self, mock_config_module, mock_get_summaries, mock_generate_theme, mock_config
    ):
        """Test when theme generation returns None."""
        mock_config_module.book_suggestions_enabled = True
        mock_config_module.books_to_analyze = 10
        mock_config_module.suggestions_ai_provider = "openai"

        mock_get_summaries.return_value = [
            VideoSummary(
                video_id="v1",
                title="Video 1",
                summary="Summary 1",
            )
        ]
        mock_generate_theme.return_value = None

        result = get_video_suggestions()

        assert len(result) == 0

    @patch("services.book_suggestions.search_youtube_by_theme")
    @patch("services.book_suggestions.generate_theme_openai")
    @patch("services.book_suggestions.get_recent_summaries")
    @patch("services.book_suggestions.config")
    def test_no_videos_found_from_search(
        self,
        mock_config_module,
        mock_get_summaries,
        mock_generate_theme,
        mock_search,
        mock_config,
    ):
        """Test when YouTube search returns no videos."""
        mock_config_module.book_suggestions_enabled = True
        mock_config_module.books_to_analyze = 10
        mock_config_module.suggestions_count = 4
        mock_config_module.suggestions_ai_provider = "openai"

        mock_get_summaries.return_value = [
            VideoSummary(
                video_id="v1",
                title="Video 1",
                summary="Summary 1",
            )
        ]
        mock_generate_theme.return_value = "test theme"
        mock_search.return_value = []  # No videos found

        result = get_video_suggestions()

        assert len(result) == 0
