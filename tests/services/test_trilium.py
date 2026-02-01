"""Tests for Trilium service."""

from unittest.mock import Mock, patch, mock_open
import pytest
import httpx
from services.trilium import (
    attach_audio_to_note,
    check_video_exists,
    create_trilium_note,
    get_note_content,
    _build_url,
    _markdown_to_html,
    _escape_text,
    _save_to_backup,
)


class TestBuildUrl:
    """Tests for URL building helper."""

    def test_build_url_basic(self):
        """Test basic URL building."""
        url = _build_url("http://localhost:8080", "etapi/notes")
        assert url == "http://localhost:8080/etapi/notes"

    def test_build_url_trailing_slash(self):
        """Test URL building with trailing slash in base."""
        url = _build_url("http://localhost:8080/", "etapi/notes")
        assert url == "http://localhost:8080/etapi/notes"

    def test_build_url_leading_slash(self):
        """Test URL building with leading slash in path."""
        url = _build_url("http://localhost:8080", "/etapi/notes")
        assert url == "http://localhost:8080/etapi/notes"

    def test_build_url_both_slashes(self):
        """Test URL building with both trailing and leading slashes."""
        url = _build_url("http://localhost:8080/", "/etapi/notes")
        assert url == "http://localhost:8080/etapi/notes"


class TestEscapeText:
    """Tests for HTML escaping."""

    def test_escape_text_ampersand(self):
        """Test escaping ampersand."""
        result = _escape_text("A & B")
        assert result == "A &amp; B"

    def test_escape_text_less_than(self):
        """Test escaping less than."""
        result = _escape_text("A < B")
        assert result == "A &lt; B"

    def test_escape_text_greater_than(self):
        """Test escaping greater than."""
        result = _escape_text("A > B")
        assert result == "A &gt; B"

    def test_escape_text_quotes(self):
        """Test escaping quotes."""
        result = _escape_text('He said "hello"')
        assert result == "He said &quot;hello&quot;"

    def test_escape_text_apostrophe(self):
        """Test escaping apostrophe."""
        result = _escape_text("It's working")
        assert result == "It&#39;s working"

    def test_escape_text_multiple(self):
        """Test escaping multiple special characters."""
        result = _escape_text("<div>A & B</div>")
        assert result == "&lt;div&gt;A &amp; B&lt;/div&gt;"


class TestMarkdownToHtml:
    """Tests for markdown to HTML conversion."""

    def test_markdown_h3_header(self):
        """Test converting ### header."""
        result = _markdown_to_html("### My Header")
        assert "<h3>My Header</h3>" in result

    def test_markdown_h2_header(self):
        """Test converting ## header."""
        result = _markdown_to_html("## My Header")
        assert "<h2>My Header</h2>" in result

    def test_markdown_h1_header(self):
        """Test converting # header."""
        result = _markdown_to_html("# My Header")
        assert "<h1>My Header</h1>" in result

    def test_markdown_bullet_dash(self):
        """Test converting - bullet points."""
        result = _markdown_to_html("- Item 1\n- Item 2")
        assert "<ul>" in result
        assert "<li>Item 1</li>" in result
        assert "<li>Item 2</li>" in result
        assert "</ul>" in result

    def test_markdown_bullet_asterisk(self):
        """Test converting * bullet points."""
        result = _markdown_to_html("* Item 1\n* Item 2")
        assert "<ul>" in result
        assert "<li>Item 1</li>" in result
        assert "</ul>" in result

    def test_markdown_bold(self):
        """Test converting **bold**."""
        result = _markdown_to_html("This is **bold** text")
        assert "<strong>bold</strong>" in result

    def test_markdown_italic(self):
        """Test converting *italic*."""
        result = _markdown_to_html("This is *italic* text")
        assert "<em>italic</em>" in result

    def test_markdown_paragraph(self):
        """Test converting regular paragraph."""
        result = _markdown_to_html("Regular paragraph")
        assert "<p>Regular paragraph</p>" in result

    def test_markdown_empty_line(self):
        """Test handling empty lines."""
        result = _markdown_to_html("Para 1\n\nPara 2")
        assert "<br>" in result

    def test_markdown_complex(self):
        """Test converting complex markdown."""
        markdown = """### Summary

- Point **one**
- Point *two*

Regular paragraph"""

        result = _markdown_to_html(markdown)

        assert "<h3>Summary</h3>" in result
        assert "<ul>" in result
        assert "<strong>one</strong>" in result
        assert "<em>two</em>" in result
        assert "<p>Regular paragraph</p>" in result

    def test_markdown_header_after_list_closes_list(self):
        """Test that list is closed when header appears."""
        markdown = """- Item 1
- Item 2
### Header"""
        result = _markdown_to_html(markdown)

        assert "</ul>" in result
        assert result.index("</ul>") < result.index("<h3>")

    def test_markdown_paragraph_after_list_closes_list(self):
        """Test that list is closed when paragraph appears."""
        markdown = """- Item 1
- Item 2
Regular paragraph"""
        result = _markdown_to_html(markdown)

        assert "</ul>" in result
        assert result.index("</ul>") < result.index("<p>Regular paragraph</p>")

    def test_markdown_empty_line_closes_list(self):
        """Test that list is closed on empty line."""
        markdown = """- Item 1
- Item 2

Next paragraph"""
        result = _markdown_to_html(markdown)

        # List should be closed before the <br>
        assert "</ul>" in result

    def test_markdown_h2_after_list(self):
        """Test H2 header after list."""
        markdown = """- Item 1
## Header 2"""
        result = _markdown_to_html(markdown)

        assert "</ul>" in result
        assert "<h2>Header 2</h2>" in result

    def test_markdown_h1_after_list(self):
        """Test H1 header after list."""
        markdown = """- Item 1
# Header 1"""
        result = _markdown_to_html(markdown)

        assert "</ul>" in result
        assert "<h1>Header 1</h1>" in result

    def test_markdown_list_at_end_closes(self):
        """Test that list is properly closed at end of text."""
        markdown = """- Item 1
- Item 2"""
        result = _markdown_to_html(markdown)

        assert "<ul>" in result
        assert "</ul>" in result


class TestCheckVideoExists:
    """Tests for checking video existence in Trilium."""

    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    def test_check_video_exists_found(self, mock_client_factory, mock_config):
        """Test finding existing video note."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        mock_response = Mock()
        mock_response.json.return_value = [{"noteId": "note123"}]
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client_factory.return_value = mock_client

        result = check_video_exists("video123")

        assert result is not None
        assert result["noteId"] == "note123"
        assert "note123" in result["url"]

    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    def test_check_video_exists_found_dict_format(
        self, mock_client_factory, mock_config
    ):
        """Test finding existing video note with dict response."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        mock_response = Mock()
        mock_response.json.return_value = {"results": [{"noteId": "note123"}]}
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client_factory.return_value = mock_client

        result = check_video_exists("video123")

        assert result is not None
        assert result["noteId"] == "note123"

    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    def test_check_video_exists_not_found(self, mock_client_factory, mock_config):
        """Test when video note doesn't exist."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client_factory.return_value = mock_client

        result = check_video_exists("video123")

        assert result is None

    @patch("services.trilium.get_config")
    def test_check_video_exists_not_configured(self, mock_config):
        """Test when Trilium is not configured."""
        config = Mock()
        config.trilium_url = None
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        result = check_video_exists("video123")

        assert result is None

    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    def test_check_video_exists_http_error(self, mock_client_factory, mock_config):
        """Test handling HTTP error."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        mock_client = Mock()
        mock_client.get.side_effect = httpx.HTTPError("Connection failed")
        mock_client_factory.return_value = mock_client

        result = check_video_exists("video123")

        assert result is None

    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    def test_check_video_exists_no_note_id_in_result(
        self, mock_client_factory, mock_config
    ):
        """Test handling response without noteId."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        mock_response = Mock()
        mock_response.json.return_value = [{"title": "Some Note"}]
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client_factory.return_value = mock_client

        result = check_video_exists("video123")

        assert result is None

    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    def test_check_video_exists_unexpected_response_format(
        self, mock_client_factory, mock_config
    ):
        """Test handling unexpected response format (neither list nor dict with results)."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        mock_response = Mock()
        # Return something unexpected like a string
        mock_response.json.return_value = "unexpected format"
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client_factory.return_value = mock_client

        result = check_video_exists("video123")

        assert result is None


class TestCreateTriliumNote:
    """Tests for creating Trilium notes."""

    @patch("services.trilium.get_video_title_from_history")
    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    def test_create_trilium_note_success(
        self, mock_client_factory, mock_config, mock_get_title
    ):
        """Test successful note creation."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        config.trilium_parent_note_id = "parent123"
        mock_config.return_value = config

        mock_get_title.return_value = "Test Video Title"

        note_response = Mock()
        note_response.json.return_value = {"note": {"noteId": "new_note123"}}
        note_response.raise_for_status = Mock()

        attr_response = Mock()
        attr_response.json.return_value = {"attributeId": "attr123"}
        attr_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.post.side_effect = [note_response, attr_response]
        mock_client_factory.return_value = mock_client

        result = create_trilium_note("video123", "transcript text", "summary text")

        assert result["noteId"] == "new_note123"
        assert "new_note123" in result["url"]
        assert mock_client.post.call_count == 2

    @patch("services.trilium.get_video_title_from_history")
    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    def test_create_trilium_note_no_title_uses_fallback(
        self, mock_client_factory, mock_config, mock_get_title
    ):
        """Test note creation with fallback title."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        config.trilium_parent_note_id = "parent123"
        mock_config.return_value = config

        mock_get_title.return_value = None

        note_response = Mock()
        note_response.json.return_value = {"note": {"noteId": "new_note123"}}
        note_response.raise_for_status = Mock()

        attr_response = Mock()
        attr_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.post.side_effect = [note_response, attr_response]
        mock_client_factory.return_value = mock_client

        create_trilium_note("video123", "transcript", "summary")

        call_args = mock_client.post.call_args_list[0]
        payload = call_args[1]["json"]
        assert "YouTube Video video123" in payload["title"]

    @patch("services.trilium.get_config")
    def test_create_trilium_note_not_configured(self, mock_config):
        """Test note creation when not configured."""
        config = Mock()
        config.trilium_url = None
        config.trilium_etapi_token = "test_token"
        config.trilium_parent_note_id = "parent123"
        mock_config.return_value = config

        with pytest.raises(ValueError, match="not properly configured"):
            create_trilium_note("video123", "transcript", "summary")

    @patch("services.trilium.get_video_title_from_history")
    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    def test_create_trilium_note_http_error_raises_exception(
        self, mock_client_factory, mock_config, mock_get_title
    ):
        """Test that HTTP errors raise exceptions."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        config.trilium_parent_note_id = "parent123"
        mock_config.return_value = config

        mock_get_title.return_value = "Test Title"

        # Simulate a status error from raise_for_status()
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Connection failed", request=Mock(), response=Mock()
        )

        mock_client = Mock()
        mock_client.post.return_value = mock_response
        mock_client_factory.return_value = mock_client

        with pytest.raises(Exception, match="Failed to create Trilium note"):
            create_trilium_note("video123", "transcript", "summary")

    @patch("services.trilium.get_video_title_from_history")
    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    def test_create_trilium_note_no_note_id_in_response(
        self, mock_client_factory, mock_config, mock_get_title
    ):
        """Test handling response without noteId."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        config.trilium_parent_note_id = "parent123"
        mock_config.return_value = config

        mock_get_title.return_value = "Test Title"

        note_response = Mock()
        note_response.json.return_value = {"note": {}}
        note_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.post.return_value = note_response
        mock_client_factory.return_value = mock_client

        with pytest.raises(Exception, match="Failed to get note ID"):
            create_trilium_note("video123", "transcript", "summary")


class TestGetNoteContent:
    """Tests for fetching note content."""

    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    def test_get_note_content_success(self, mock_client_factory, mock_config):
        """Test successful note content fetch."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        mock_response = Mock()
        mock_response.text = "<h3>Summary</h3><p>Note content here</p>"
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client_factory.return_value = mock_client

        result = get_note_content("note123")

        assert result == "<h3>Summary</h3><p>Note content here</p>"
        assert mock_client.get.called

    @patch("services.trilium.get_config")
    def test_get_note_content_not_configured(self, mock_config):
        """Test when Trilium is not configured."""
        config = Mock()
        config.trilium_url = None
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        result = get_note_content("note123")

        assert result is None

    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    def test_get_note_content_http_error(self, mock_client_factory, mock_config):
        """Test handling HTTP error."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        mock_client = Mock()
        mock_client.get.side_effect = httpx.HTTPError("Connection failed")
        mock_client_factory.return_value = mock_client

        result = get_note_content("note123")

        assert result is None


class TestAttachAudioToNote:
    """Tests for attaching audio files to Trilium notes."""

    @patch("builtins.open", new_callable=mock_open, read_data=b"fake audio data")
    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    @patch("httpx.Client")
    def test_attach_audio_success(
        self, mock_httpx_client_class, mock_client_factory, mock_config, mock_file
    ):
        """Test successful audio attachment."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        # Mock note creation response
        note_response = Mock()
        note_response.json.return_value = {"note": {"noteId": "audio_note123"}}
        note_response.raise_for_status = Mock()

        # Mock content upload response
        content_response = Mock()
        content_response.status_code = 200
        content_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.post.return_value = note_response
        mock_client_factory.return_value = mock_client

        # Mock upload client
        mock_upload_client = Mock()
        mock_upload_client.put.return_value = content_response
        mock_upload_client.__enter__ = Mock(return_value=mock_upload_client)
        mock_upload_client.__exit__ = Mock(return_value=None)
        mock_httpx_client_class.return_value = mock_upload_client

        result = attach_audio_to_note(
            note_id="parent123", audio_file_path="/tmp/audio.mp3", title="audio.mp3"
        )

        assert result["noteId"] == "audio_note123"
        assert result["status"] == "success"
        assert mock_client.post.called
        assert mock_upload_client.put.called

    @patch("services.trilium.get_config")
    def test_attach_audio_not_configured(self, mock_config):
        """Test when Trilium is not configured."""
        config = Mock()
        config.trilium_url = None
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        with pytest.raises(ValueError, match="not properly configured"):
            attach_audio_to_note("note123", "/tmp/audio.mp3", "audio.mp3")

    @patch("builtins.open", new_callable=mock_open, read_data=b"fake audio data")
    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    def test_attach_audio_note_creation_fails(
        self, mock_client_factory, mock_config, mock_file
    ):
        """Test when note creation fails."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        # Mock note creation response without noteId
        note_response = Mock()
        note_response.json.return_value = {"note": {}}
        note_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.post.return_value = note_response
        mock_client_factory.return_value = mock_client

        with pytest.raises(Exception, match="Failed to get note ID"):
            attach_audio_to_note("note123", "/tmp/audio.mp3", "audio.mp3")

    @patch("builtins.open", new_callable=mock_open, read_data=b"fake audio data")
    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    @patch("httpx.Client")
    def test_attach_audio_upload_fails(
        self, mock_httpx_client_class, mock_client_factory, mock_config, mock_file
    ):
        """Test when audio upload fails."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        # Mock note creation success
        note_response = Mock()
        note_response.json.return_value = {"note": {"noteId": "audio_note123"}}
        note_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.post.return_value = note_response
        mock_client_factory.return_value = mock_client

        # Mock upload client that fails
        content_response = Mock()
        content_response.status_code = 500
        content_response.text = "Internal Server Error"
        content_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Upload failed", request=Mock(), response=content_response
        )

        mock_upload_client = Mock()
        mock_upload_client.put.return_value = content_response
        mock_upload_client.__enter__ = Mock(return_value=mock_upload_client)
        mock_upload_client.__exit__ = Mock(return_value=None)
        mock_httpx_client_class.return_value = mock_upload_client

        with pytest.raises(Exception):
            attach_audio_to_note("note123", "/tmp/audio.mp3", "audio.mp3")

    @patch("builtins.open", side_effect=IOError("File read error"))
    @patch("services.trilium.get_config")
    @patch("services.trilium.get_httpx_client")
    def test_attach_audio_file_read_fails_backup_also_fails(
        self, mock_client_factory, mock_config, mock_file
    ):
        """Test when audio file read fails and backup save also fails."""
        config = Mock()
        config.trilium_url = "http://localhost:8080"
        config.trilium_etapi_token = "test_token"
        mock_config.return_value = config

        # Mock note creation success
        note_response = Mock()
        note_response.json.return_value = {"note": {"noteId": "audio_note123"}}
        note_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.post.return_value = note_response
        mock_client_factory.return_value = mock_client

        # This should raise the file read exception
        # The backup will also fail because open() is mocked to always fail
        with pytest.raises(Exception):
            attach_audio_to_note("note123", "/tmp/audio.mp3", "audio.mp3")


class TestSaveToBackup:
    """Tests for backup save function."""

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_save_to_backup_success(self, mock_makedirs, mock_file):
        """Test successful backup save."""
        _save_to_backup("video123", "transcript text", "summary text")

        mock_makedirs.assert_called_once_with("/tmp/trilium-backup", exist_ok=True)
        mock_file.assert_called_once_with("/tmp/trilium-backup/video123.json", "w")

    @patch("builtins.open", side_effect=Exception("Write error"))
    @patch("os.makedirs")
    def test_save_to_backup_fails_gracefully(self, mock_makedirs, mock_file):
        """Test that backup failure doesn't raise exception."""
        # Should not raise exception, just log error
        _save_to_backup("video123", "transcript", "summary")
