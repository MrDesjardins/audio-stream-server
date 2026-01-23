"""Trilium Notes integration using ETAPI."""
import logging
import json
import os
from typing import Optional, Dict
import httpx

from config import get_config
from services.database import get_video_title_from_history

logger = logging.getLogger(__name__)


def _build_url(base_url: str, path: str) -> str:
    """Build a URL by joining base and path, handling trailing/leading slashes."""
    base = base_url.rstrip('/')
    path = path.lstrip('/')
    return f"{base}/{path}"


def check_video_exists(video_id: str) -> Optional[Dict[str, str]]:
    """
    Check if a note already exists in Trilium for this video using attributes.

    Args:
        video_id: The YouTube video ID

    Returns:
        Dict with noteId and url if exists, None otherwise
    """
    config = get_config()

    if not all([config.trilium_url, config.trilium_etapi_token]):
        logger.warning("Trilium not configured, skipping deduplication check")
        return None

    try:
        logger.info(f"Searching for existing note with youtube_id={video_id}")

        headers = {
            "Authorization": f"Bearer {config.trilium_etapi_token}",
            "Content-Type": "application/json"
        }

        # Search for notes with youtube_id attribute
        # Using the search endpoint to find notes by attribute
        search_query = f'#youtube_id="{video_id}"'
        url = _build_url(config.trilium_url, "etapi/notes")

        # Try to search using query parameter
        params = {"search": search_query}
        response = httpx.get(url, headers=headers, params=params, timeout=10.0)
        response.raise_for_status()

        results = response.json()

        # The search endpoint returns a list directly (or might have "results" key)
        # Handle both possible response formats
        if isinstance(results, dict) and "results" in results:
            # Response is {"results": [...]}
            note_list = results.get("results", [])
        elif isinstance(results, list):
            # Response is directly a list
            note_list = results
        else:
            logger.warning(f"Unexpected search response format: {type(results)}")
            note_list = []

        if note_list and len(note_list) > 0:
            # Get the first result
            first_note = note_list[0]
            note_id = first_note.get("noteId")

            if not note_id:
                logger.warning(f"Found search result but no noteId in response: {first_note}")
                return None

            logger.info(f"Found existing note for video {video_id}: {note_id}")
            # Construct note URL - hash fragment should be appended directly
            note_url = f"{config.trilium_url.rstrip('/')}/#root/{note_id}"
            return {
                "noteId": note_id,
                "url": note_url
            }

        logger.info(f"No existing note found for video {video_id}")
        return None

    except Exception as e:
        logger.warning(f"Could not check Trilium for existing note (will skip deduplication): {e}")
        # Don't fail the entire process, just continue without deduplication
        return None


def create_trilium_note(video_id: str, transcript: str, summary: str) -> Dict[str, str]:
    """
    Create a new note in Trilium with the summary and youtube_id attribute.

    Args:
        video_id: The YouTube video ID
        transcript: The full transcript text (saved to cache but not posted)
        summary: The summary text

    Returns:
        Dict with noteId and url

    Raises:
        Exception: If note creation fails
    """
    config = get_config()

    if not all([config.trilium_url, config.trilium_etapi_token, config.trilium_parent_note_id]):
        raise ValueError("Trilium not properly configured")

    try:
        logger.info(f"Creating Trilium note for video {video_id}")

        # Get video title from database
        video_title = get_video_title_from_history(video_id)
        if not video_title:
            video_title = f"YouTube Video {video_id}"
            logger.warning(f"No title found in history for {video_id}, using fallback")

        # Convert markdown-style formatting to HTML
        summary_html = _markdown_to_html(summary)

        # Format content as HTML - only summary, no transcript
        content = f"""<div class="youtube-summary">
{summary_html}
</div>

<p style="margin-top: 2em; padding-top: 1em; border-top: 1px solid #ccc;">
    <strong>YouTube:</strong> <a href="https://www.youtube.com/watch?v={video_id}" target="_blank">Watch Video</a>
</p>
"""

        headers = {
            "Authorization": config.trilium_etapi_token,
            "Content-Type": "application/json"
        }

        # Step 1: Create the note (without attributes)
        payload = {
            "parentNoteId": config.trilium_parent_note_id,
            "title": video_title,
            "type": "text",
            "mime": "text/html",
            "content": content
        }

        url = _build_url(config.trilium_url, "etapi/create-note")
        response = httpx.post(url, headers=headers, json=payload, timeout=30.0)
        response.raise_for_status()

        result = response.json()
        note_id = result.get("note", {}).get("noteId")

        if not note_id:
            raise Exception(f"Failed to get note ID from response: {result}")

        logger.info(f"Created Trilium note: {note_id}")

        # Step 2: Add the youtube_id attribute to the note
        attribute_payload = {
            "noteId": note_id,
            "type": "label",
            "name": "youtube_id",
            "value": video_id
        }

        attribute_url = _build_url(config.trilium_url, "etapi/attributes")
        attr_response = httpx.post(attribute_url, headers=headers, json=attribute_payload, timeout=30.0)
        attr_response.raise_for_status()

        logger.info(f"Added youtube_id attribute to note {note_id}")

        # Construct note URL - hash fragment should be appended directly
        note_url = f"{config.trilium_url.rstrip('/')}/#root/{note_id}"
        logger.info(f"Successfully created Trilium note: {note_id} with youtube_id attribute")
        return {
            "noteId": note_id,
            "url": note_url
        }

    except httpx.HTTPError as e:
        logger.error(f"HTTP error creating Trilium note: {e}")
        logger.error(f"Check that TRILIUM_URL ({config.trilium_url}) is correct and Trilium is running")
        logger.error(f"Check that TRILIUM_PARENT_NOTE_ID ({config.trilium_parent_note_id}) exists")
        # Save to backup file
        _save_to_backup(video_id, transcript, summary)
        raise Exception(f"Failed to create Trilium note (check logs for details): {e}")

    except Exception as e:
        logger.error(f"Error creating Trilium note: {e}")
        # Save to backup file
        _save_to_backup(video_id, transcript, summary)
        raise


def _markdown_to_html(text: str) -> str:
    """
    Convert basic markdown formatting to HTML.

    Handles:
    - ### Headers
    - **bold**
    - Bullet points (-, *)
    - Line breaks
    """
    lines = text.split('\n')
    html_lines = []
    in_list = False

    for line in lines:
        line = line.strip()

        if not line:
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append('<br>')
            continue

        # Handle headers (###, ##, #)
        if line.startswith('### '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append(f'<h3>{_escape_text(line[4:])}</h3>')
        elif line.startswith('## '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append(f'<h2>{_escape_text(line[3:])}</h2>')
        elif line.startswith('# '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append(f'<h1>{_escape_text(line[2:])}</h1>')

        # Handle bullet points
        elif line.startswith('- ') or line.startswith('* '):
            if not in_list:
                html_lines.append('<ul>')
                in_list = True
            content = line[2:].strip()
            # Handle bold within list items
            content = _process_inline_formatting(content)
            html_lines.append(f'<li>{content}</li>')

        # Regular paragraph
        else:
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            content = _process_inline_formatting(line)
            html_lines.append(f'<p>{content}</p>')

    # Close any open list
    if in_list:
        html_lines.append('</ul>')

    return '\n'.join(html_lines)


def _process_inline_formatting(text: str) -> str:
    """Process inline formatting like **bold**."""
    import re

    # Escape HTML first
    text = _escape_text(text)

    # Handle **bold**
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)

    # Handle *italic*
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)

    return text


def _escape_text(text: str) -> str:
    """Escape HTML special characters in text."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))


def _save_to_backup(video_id: str, transcript: str, summary: str) -> None:
    """Save transcript and summary to local backup file."""
    try:
        backup_dir = "/tmp/trilium-backup"
        os.makedirs(backup_dir, exist_ok=True)

        backup_file = os.path.join(backup_dir, f"{video_id}.json")

        data = {
            "video_id": video_id,
            "transcript": transcript,
            "summary": summary,
            "youtube_url": f"https://www.youtube.com/watch?v={video_id}"
        }

        with open(backup_file, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved backup to {backup_file}")

    except Exception as e:
        logger.error(f"Failed to save backup file: {e}")
