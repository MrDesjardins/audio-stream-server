"""Tests for YouTube service."""
import json
import subprocess
from unittest.mock import Mock, patch, MagicMock
import pytest
from services.youtube import get_video_title, extract_video_id


class TestExtractVideoId:
    """Tests for video ID extraction."""

    def test_extract_video_id_from_plain_id(self):
        """Test extracting ID when already a plain ID."""
        video_id = "dQw4w9WgXcQ"
        result = extract_video_id(video_id)
        assert result == video_id

    def test_extract_video_id_from_watch_url(self):
        """Test extracting ID from youtube.com/watch URL."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        result = extract_video_id(url)
        assert result == "dQw4w9WgXcQ"

    def test_extract_video_id_from_short_url(self):
        """Test extracting ID from youtu.be short URL."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        result = extract_video_id(url)
        assert result == "dQw4w9WgXcQ"

    def test_extract_video_id_from_embed_url(self):
        """Test extracting ID from embed URL."""
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        result = extract_video_id(url)
        assert result == "dQw4w9WgXcQ"

    def test_extract_video_id_with_timestamp(self):
        """Test extracting ID from URL with timestamp."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s"
        result = extract_video_id(url)
        assert result == "dQw4w9WgXcQ"

    def test_extract_video_id_with_playlist(self):
        """Test extracting ID from URL with playlist parameter."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLxyz"
        result = extract_video_id(url)
        assert result == "dQw4w9WgXcQ"

    def test_extract_video_id_invalid_returns_trimmed(self):
        """Test that invalid input returns trimmed string."""
        invalid = "not a valid id or url"
        result = extract_video_id(invalid)
        assert result == "not a valid id or url"

    def test_extract_video_id_strips_whitespace(self):
        """Test that whitespace is stripped."""
        video_id = "  dQw4w9WgXcQ  "
        result = extract_video_id(video_id)
        assert result == "dQw4w9WgXcQ"


class TestGetVideoTitle:
    """Tests for video title fetching."""

    @patch('services.youtube.subprocess.run')
    def test_get_video_title_success(self, mock_run):
        """Test successfully getting video title."""
        # Mock successful yt-dlp response
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "title": "Test Video Title",
            "id": "dQw4w9WgXcQ"
        })
        mock_run.return_value = mock_result

        title = get_video_title("dQw4w9WgXcQ")

        assert title == "Test Video Title"

        # Verify subprocess was called correctly
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "--dump-json" in call_args[0][0]
        assert "--no-playlist" in call_args[0][0]

    @patch('services.youtube.subprocess.run')
    def test_get_video_title_failure(self, mock_run):
        """Test handling yt-dlp failure."""
        # Mock failed yt-dlp response
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        title = get_video_title("invalid_id")

        assert title is None

    @patch('services.youtube.subprocess.run')
    def test_get_video_title_invalid_json(self, mock_run):
        """Test handling invalid JSON response."""
        # Mock yt-dlp returning invalid JSON
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "not valid json"
        mock_run.return_value = mock_result

        title = get_video_title("dQw4w9WgXcQ")

        assert title is None

    @patch('services.youtube.subprocess.run')
    def test_get_video_title_timeout(self, mock_run):
        """Test handling subprocess timeout."""
        # Mock subprocess timeout
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="yt-dlp", timeout=10)

        title = get_video_title("dQw4w9WgXcQ")

        assert title is None

    @patch('services.youtube.subprocess.run')
    def test_get_video_title_no_title_field(self, mock_run):
        """Test handling response without title field."""
        # Mock response without title
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "id": "dQw4w9WgXcQ",
            "description": "Some description"
        })
        mock_run.return_value = mock_result

        title = get_video_title("dQw4w9WgXcQ")

        assert title == "Unknown Title"

    @patch('services.youtube.subprocess.run')
    def test_get_video_title_exception(self, mock_run):
        """Test handling general exception."""
        # Mock subprocess raising exception
        mock_run.side_effect = Exception("Network error")

        title = get_video_title("dQw4w9WgXcQ")

        assert title is None
