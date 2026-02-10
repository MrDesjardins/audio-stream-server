"""
Weekly audiobook summary service.

Generates a comprehensive summary of all audiobooks read during the week,
including overview, key learnings, and common themes.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

from config import get_config
from services.api_clients import get_httpx_client
from services.llm_clients import get_tracked_gemini_client, get_tracked_openai_client
from services.database import get_history, get_summary_by_week_year, save_weekly_summary
from services.path_utils import expand_path
from services.trilium import (
    check_video_exists,
    get_note_content,
    _build_url,
    _get_trilium_headers,
    _get_trilium_note_url,
    _markdown_to_html,
    attach_audio_to_note,
)
from services.tts import (
    generate_audio,
    save_audio_file,
    extract_summary_text_for_tts,
    get_audio_duration,
)

logger = logging.getLogger(__name__)
config = get_config()


def get_week_number(date: datetime) -> tuple[int, int]:
    """
    Get year and week number for a given date.

    Args:
        date: Date to get week number for

    Returns:
        Tuple of (year, week_number)
    """
    iso_calendar = date.isocalendar()
    return (iso_calendar[0], iso_calendar[1])


def _fetch_youtube_id_from_note(note: Dict) -> Optional[Dict[str, str]]:
    """
    Fetch YouTube ID from a Trilium note's attributes.

    Args:
        note: Trilium note dict with noteId and title

    Returns:
        Dict with video_id and title if found, None otherwise
    """
    try:
        client = get_httpx_client()
        note_id = note.get("noteId")
        title = note.get("title", "Unknown Title")

        # Fetch attributes to get youtube_id
        attr_url = _build_url(config.trilium_url, f"/etapi/notes/{note_id}/attributes")
        attr_response = client.get(attr_url, headers=_get_trilium_headers(), timeout=10)

        if attr_response.status_code == 200:
            attributes = attr_response.json()
            for attr in attributes:
                if attr.get("name") == "youtube_id":
                    video_id = attr.get("value")
                    if video_id:
                        return {"video_id": video_id, "title": title}
                    break

        return None

    except Exception as e:
        logger.error(f"Error fetching YouTube ID from note {note.get('noteId')}: {e}")
        return None


def get_books_from_trilium_last_week() -> List[Dict[str, str]]:
    """
    Get all books from Trilium that were created in the last 7 days.

    This uses Trilium as the source of truth instead of the play history database.
    More reliable for weekly summaries since it only includes books with summaries.

    Returns:
        List of dicts with video_id, title
    """
    try:
        client = get_httpx_client()

        # Calculate date 7 days ago
        cutoff_date = datetime.now() - timedelta(days=7)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")

        # Search for notes with youtube_id attribute created in last 7 days
        # Note: Trilium's search syntax for date ranges
        search_query = f"#youtube_id note.dateCreated >= '{cutoff_str}'"

        url = _build_url(config.trilium_url, "/etapi/notes")
        params = {"search": search_query}

        response = client.get(
            url, params=params, headers=_get_trilium_headers(), timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])

            weekly_books = []
            for note in results:
                book = _fetch_youtube_id_from_note(note)
                if book:
                    weekly_books.append(book)

            logger.info(f"Found {len(weekly_books)} books from Trilium (last 7 days)")
            return weekly_books
        else:
            logger.error(
                f"Failed to search Trilium: {response.status_code} - {response.text}"
            )
            return []

    except Exception as e:
        logger.error(f"Error getting books from Trilium: {e}", exc_info=True)
        return []


def _is_played_within_last_week(
    item, cutoff_date: datetime
) -> Optional[Dict[str, str]]:
    """
    Check if a history item was played within the last week.

    Args:
        item: PlayHistoryItem to check
        cutoff_date: Cutoff datetime for filtering

    Returns:
        Dict with video_id, title, last_played_at if played recently, None otherwise
    """
    try:
        played_at_str = item.last_played_at.replace("Z", "+00:00")
        played_at = datetime.fromisoformat(played_at_str)

        # Convert to naive datetime for comparison if it's timezone-aware
        if played_at.tzinfo is not None:
            played_at = played_at.replace(tzinfo=None)

        if played_at >= cutoff_date:
            return {
                "video_id": item.youtube_id,
                "title": item.title,
                "last_played_at": item.last_played_at,
            }
        return None

    except Exception as e:
        logger.error(f"Error parsing date for {item.youtube_id}: {e}")
        return None


def get_books_from_last_week() -> List[Dict[str, str]]:
    """
    Get all books played in the last 7 days.

    Returns:
        List of dicts with video_id, title, last_played_at
    """
    try:
        # Get history from last 7 days
        history = get_history(limit=1000)  # Get enough to cover the week

        if not history:
            logger.warning("No history found")
            return []

        # Filter to last 7 days (use naive datetime for comparison)
        cutoff_date = datetime.now() - timedelta(days=7)
        weekly_books = []

        for item in history:
            book = _is_played_within_last_week(item, cutoff_date)
            if book:
                weekly_books.append(book)

        logger.info(f"Found {len(weekly_books)} books played in the last week")
        return weekly_books

    except Exception as e:
        logger.error(f"Error getting books from last week: {e}", exc_info=True)
        return []


def _fetch_summary_for_book(book: Dict[str, str]) -> Optional[Dict[str, str]]:
    """
    Fetch summary for a single book from Trilium.

    Args:
        book: Book dict with video_id and title

    Returns:
        Dict with video_id, title, summary, note_url, or None if not found
    """
    video_id = book["video_id"]
    title = book["title"]

    try:
        # Check if note exists in Trilium
        note_info = check_video_exists(video_id)

        if not note_info:
            logger.warning(f"No Trilium note found for {title}")
            return None

        note_id = note_info["noteId"]
        note_url = note_info.get("url", f"{config.trilium_url}/#root/{note_id}")

        # Fetch note content
        content = get_note_content(note_id)

        if not content:
            logger.warning(f"Could not fetch note content for {title}")
            return None

        # Extract summary from HTML content
        # Remove the YouTube link section at the bottom
        content = re.sub(r'<p style="margin-top.*?</p>', "", content, flags=re.DOTALL)

        # Strip HTML tags to get plain text
        text_summary = re.sub(r"<[^>]+>", " ", content)
        # Clean up whitespace
        text_summary = re.sub(r"\s+", " ", text_summary).strip()

        if not text_summary:
            logger.warning(f"Empty summary for {title}")
            return None

        logger.debug(f"Fetched summary for {title}")
        return {
            "video_id": video_id,
            "title": title,
            "summary": text_summary,
            "note_url": note_url,
        }

    except Exception as e:
        logger.error(f"Error fetching summary for {video_id}: {e}")
        return None


def fetch_book_summaries(books: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Fetch summaries from Trilium for the given books.

    Args:
        books: List of book dicts with video_id and title

    Returns:
        List of dicts with video_id, title, summary, note_url
    """
    summaries = []

    for book in books:
        summary = _fetch_summary_for_book(book)
        if summary:
            summaries.append(summary)

    logger.info(f"Fetched {len(summaries)} summaries out of {len(books)} books")
    return summaries


def _build_weekly_summary_prompt(summaries: List[Dict[str, str]]) -> str:
    """
    Build the prompt for weekly summary generation.

    Args:
        summaries: List of book summaries

    Returns:
        Formatted prompt string
    """
    summaries_text = "\n\n---\n\n".join(
        f"**{s['title']}**\n\n{s['summary']}" for s in summaries
    )

    return f"""You are analyzing audiobook summaries from the past week. Below are {len(summaries)} book summaries:

{summaries_text}

Please create a comprehensive weekly reading summary with the following sections:

## Overview
Write a 2-3 paragraph overview of the week's reading, highlighting the variety of topics covered and any notable patterns.

## 15 Most Important Learnings
List the 15 most important, actionable, and impactful learnings from across all the books. Each learning should be:
- Specific and actionable
- Stand-alone (understandable without full context)
- Represent diverse topics from different books
- Numbered 1-15

Format as:
1. **[Topic/Book Theme]**: [Specific learning or insight]
2. ...

## Common Themes
Analyze the books to identify 3-5 recurring themes, patterns, or concepts that appeared across multiple books. For each theme:
- Name the theme
- Explain how it appeared in different books
- Provide synthesis/connection between the books
- Make it insightful and thought-provoking

Format each theme as a subsection with explanation.

Write in markdown format. Be insightful, synthesis-focused, and highlight connections between books."""


def generate_weekly_summary_openai(summaries: List[Dict[str, str]]) -> Optional[str]:
    """
    Generate weekly summary using OpenAI.

    Args:
        summaries: List of book summaries

    Returns:
        Generated weekly summary in markdown format
    """
    try:
        config = get_config()
        client = get_tracked_openai_client()

        prompt = _build_weekly_summary_prompt(summaries)

        messages = [
            {
                "role": "system",
                "content": "You are an expert at analyzing and synthesizing insights from books. You identify patterns, extract key learnings, and find connections across diverse topics.",
            },
            {"role": "user", "content": prompt},
        ]

        metadata = {"book_count": len(summaries)}

        response = client.create_chat_completion(
            messages=messages,
            feature="weekly_summary",
            metadata=metadata,
            temperature=0.7,
            max_tokens=3500,
            model_override=config.weekly_summary_model,
        )

        summary = response.choices[0].message.content
        if summary:
            summary = summary.strip()
            logger.info(f"Generated weekly summary ({len(summary)} chars)")
            return summary
        else:
            logger.error("Empty response from OpenAI")
            return None

    except Exception as e:
        logger.error(f"Error generating summary with OpenAI: {e}", exc_info=True)
        return None


def generate_weekly_summary_gemini(summaries: List[Dict[str, str]]) -> Optional[str]:
    """
    Generate weekly summary using Gemini.

    Args:
        summaries: List of book summaries

    Returns:
        Generated weekly summary in markdown format
    """
    try:
        config = get_config()
        client = get_tracked_gemini_client()

        prompt = _build_weekly_summary_prompt(summaries)

        metadata = {"book_count": len(summaries)}

        response = client.generate_content(
            prompt=prompt,
            feature="weekly_summary",
            metadata=metadata,
            model_override=config.weekly_summary_model,
        )

        summary = response.text
        if summary:
            summary = summary.strip()
            logger.info(f"Generated weekly summary ({len(summary)} chars)")
            return summary
        else:
            logger.error("Empty response from Gemini")
            return None

    except Exception as e:
        logger.error(f"Error generating summary with Gemini: {e}", exc_info=True)
        return None


def create_weekly_summary_note(
    summary_content: str, book_links: List[Dict[str, str]], year: int, week: int
) -> Optional[Dict[str, str]]:
    """
    Create a Trilium note with the weekly summary.

    Args:
        summary_content: Generated summary content (markdown)
        book_links: List of books with titles and URLs
        year: Year number
        week: Week number

    Returns:
        Dict with noteId and url, or None on failure
    """
    try:
        # Build the note title
        note_title = f"Summary of week {year}-W{week:02d}"

        # Build book list section
        books_html = "<h3>Books Read This Week</h3>\n<ul>\n"
        for book in book_links:
            books_html += (
                f'  <li><a href="{book["note_url"]}">{book["title"]}</a></li>\n'
            )
        books_html += "</ul>\n\n"

        # Convert markdown summary to HTML
        summary_html = _markdown_to_html(summary_content)

        # Combine into final HTML
        full_html = books_html + summary_html

        # Create the note
        client = get_httpx_client()
        url = _build_url(config.trilium_url, "/etapi/create-note")

        payload = {
            "parentNoteId": config.trilium_parent_note_id,
            "title": note_title,
            "type": "text",
            "content": full_html,
            "mime": "text/html",
        }

        response = client.post(
            url, json=payload, headers=_get_trilium_headers(), timeout=30
        )

        if response.status_code == 201:
            data = response.json()
            note_id = data.get("note", {}).get("noteId")

            if note_id:
                note_url = f"{config.trilium_url}/#root/{note_id}"
                logger.info(f"Created weekly summary note: {note_title} ({note_id})")

                # Add attribute to mark as weekly summary
                attr_url = _build_url(config.trilium_url, "/etapi/attributes")
                attr_payload = {
                    "noteId": note_id,
                    "type": "label",
                    "name": "weekly_summary",
                    "value": f"{year}-W{week:02d}",
                }

                attr_response = client.post(
                    attr_url,
                    json=attr_payload,
                    headers=_get_trilium_headers(),
                    timeout=10,
                )

                if attr_response.status_code != 201:
                    logger.warning(
                        f"Failed to add attribute to weekly summary note: {attr_response.text}"
                    )

                return {"noteId": note_id, "url": note_url}
            else:
                logger.error("No noteId in response")
                return None
        else:
            logger.error(
                f"Failed to create note: {response.status_code} - {response.text}"
            )
            return None

    except Exception as e:
        logger.error(f"Error creating weekly summary note: {e}", exc_info=True)
        return None


def _verify_trilium_note_exists(note_id: str) -> bool:
    """
    Verify that a Trilium note still exists.

    Args:
        note_id: The Trilium note ID to check

    Returns:
        True if note exists, False if deleted (404) or on error
    """
    try:
        client = get_httpx_client()
        note_url = _build_url(config.trilium_url, f"etapi/notes/{note_id}")
        response = client.get(note_url, headers=_get_trilium_headers(), timeout=10.0)

        if response.status_code == 404:
            logger.warning(
                f"Trilium note {note_id} no longer exists (404). "
                f"Database entry is stale."
            )
            return False
        elif response.status_code != 200:
            logger.warning(
                f"Could not verify Trilium note {note_id}: HTTP {response.status_code}. "
                f"Proceeding anyway..."
            )
        return True
    except Exception as e:
        logger.warning(
            f"Could not verify Trilium note {note_id}: {e}. Proceeding anyway..."
        )
        return True


def _check_audio_already_attached(note_id: str, filename: str) -> bool:
    """
    Check if audio file is already attached to a Trilium note.

    Args:
        note_id: The Trilium note ID
        filename: Expected filename (e.g., "2024-W01.mp3")

    Returns:
        True if audio is already attached, False otherwise
    """
    try:
        client = get_httpx_client()
        children_url = _build_url(config.trilium_url, f"etapi/notes/{note_id}/children")
        response = client.get(
            children_url, headers=_get_trilium_headers(), timeout=10.0
        )
        response.raise_for_status()

        children = response.json()
        return any(child.get("title") == filename for child in children)
    except Exception as e:
        logger.warning(f"Could not check Trilium children: {e}")
        return False


def _generate_and_attach_tts(
    note_id: str, week_year: str, year: int, week: int, note_title: str
) -> Optional[Dict[str, str]]:
    """
    Generate TTS audio for a weekly summary and attach to Trilium note.

    Args:
        note_id: The Trilium note ID
        week_year: Week identifier (e.g., "2024-W01")
        year: Year number
        week: Week number
        note_title: Title of the note

    Returns:
        Dict with noteId and url on success, None on failure
    """
    if not config.tts_enabled:
        logger.info("TTS not enabled")
        return {"noteId": note_id, "url": _get_trilium_note_url(note_id)}

    try:
        audio_path = config.get_weekly_summary_audio_path(week_year)

        # Check if audio file already exists
        if expand_path(audio_path).exists():
            logger.info(f"Audio file already exists: {audio_path}")
            duration = get_audio_duration(audio_path)
            if duration is None:
                duration = 0
        else:
            # Generate new audio
            logger.info("Generating TTS audio...")
            note_content = get_note_content(note_id)
            if not note_content:
                raise Exception("Could not fetch note content")

            tts_text = extract_summary_text_for_tts(note_content)
            if not tts_text or len(tts_text) < 50:
                raise Exception("Text too short for TTS")

            logger.info(
                f"Generating TTS audio with {config.tts_provider} ({len(tts_text)} chars)..."
            )

            # Get provider-specific settings
            if config.tts_provider == "openai":
                if not config.openai_api_key:
                    raise ValueError("OpenAI API key not configured")
                api_key = config.openai_api_key
                voice = config.openai_tts_voice
                model = config.openai_tts_model
            else:  # elevenlabs
                if not config.elevenlabs_api_key:
                    raise ValueError("ElevenLabs API key not configured")
                api_key = config.elevenlabs_api_key
                voice = config.elevenlabs_voice_id
                model = config.elevenlabs_model_id

            audio_data = generate_audio(
                text=tts_text,
                api_key=api_key,
                provider=config.tts_provider,
                voice=voice,
                model=model,
            )
            duration = save_audio_file(audio_data, audio_path)
            logger.info(f"Saved audio file: {audio_path} ({duration}s)")

        # Check if already attached
        if not _check_audio_already_attached(note_id, f"{week_year}.mp3"):
            attach_result = attach_audio_to_note(
                note_id=note_id, audio_file_path=audio_path, title=f"{week_year}.mp3"
            )
            logger.info(f"Attached audio to Trilium: {attach_result}")

        # Update database
        save_weekly_summary(
            week_year=week_year,
            year=year,
            week=week,
            title=note_title,
            trilium_note_id=note_id,
            audio_file_path=audio_path,
            duration_seconds=duration,
        )

        return {"noteId": note_id, "url": _get_trilium_note_url(note_id)}

    except Exception as e:
        logger.error(f"TTS generation failed: {e}", exc_info=True)
        if "Could not fetch note content" in str(e):
            return None
        return {"noteId": note_id, "url": _get_trilium_note_url(note_id)}


def generate_and_save_weekly_summary(
    target_date: Optional[datetime] = None,
) -> Optional[Dict[str, str]]:
    """
    Main function to generate and save weekly summary.

    This is called by the scheduler every Friday at 11pm Pacific.

    Args:
        target_date: Optional datetime to generate summary for.
                     If None, uses current date. Used to generate summaries for past weeks.

    Behavior for existing summaries:
    - If audio file exists on disk:
      - Check if already attached to Trilium note
      - If yes: Skip completely ✅
      - If no: Attach existing file (saves TTS cost) 💰
    - If audio file doesn't exist on disk:
      - Generate TTS audio
      - Attach to Trilium note

    Behavior for new summaries:
    - Generate full summary content
    - Create Trilium note
    - Check if audio file exists on disk (e.g., from previous failed run)
    - If yes: Use existing file (saves TTS cost) 💰
    - If no: Generate TTS audio
    - Attach to Trilium note

    Returns:
        Dict with noteId and url of created note, or None on failure
    """
    try:
        logger.info("Starting weekly summary generation")

        # Get week number for target date (defaults to current date)
        now = target_date if target_date else datetime.now(timezone.utc)
        year, week = get_week_number(now)
        week_year = f"{year}-W{week:02d}"
        logger.info(f"Generating summary for week {week_year}")

        # Check if summary already exists
        existing_summary = get_summary_by_week_year(week_year)

        if existing_summary:
            logger.info(f"Summary for {week_year} already exists in database")

            note_id = existing_summary.trilium_note_id
            note_title = existing_summary.title

            # Verify the Trilium note still exists
            if note_id and not _verify_trilium_note_exists(note_id):
                logger.warning("Regenerating summary...")
                existing_summary = None

        if existing_summary:
            # Note exists in Trilium, handle TTS if needed
            if not note_id:
                raise ValueError("Existing summary has no Trilium note ID")
            return _generate_and_attach_tts(
                note_id=note_id,
                week_year=week_year,
                year=year,
                week=week,
                note_title=note_title,
            )

        # No existing summary - proceed with full generation
        logger.info("No existing summary found, proceeding with full generation")

        # Step 1: Get books from last week (prefer Trilium as source of truth)
        logger.info("Fetching books from Trilium (last 7 days)...")
        books = get_books_from_trilium_last_week()

        # Fallback to database if Trilium search fails
        if not books:
            logger.info("No books from Trilium, trying database history...")
            books = get_books_from_last_week()

        if not books:
            logger.warning("No books found in the last week, skipping summary")
            return None

        logger.info(f"Found {len(books)} books to summarize")

        # Step 2: Fetch summaries from Trilium
        summaries = fetch_book_summaries(books)
        if not summaries:
            logger.warning("No summaries found in Trilium, skipping weekly summary")
            return None

        logger.info(f"Fetched {len(summaries)} summaries from Trilium")

        # Step 3: Generate weekly summary using AI
        if config.weekly_summary_provider == "openai":
            summary_content = generate_weekly_summary_openai(summaries)
        elif config.weekly_summary_provider == "gemini":
            summary_content = generate_weekly_summary_gemini(summaries)
        else:
            logger.error(
                f"Invalid weekly summary provider: {config.weekly_summary_provider}"
            )
            return None

        if not summary_content:
            logger.error("Failed to generate summary content")
            return None

        # Step 4: Create Trilium note with summary
        note_info = create_weekly_summary_note(summary_content, summaries, year, week)

        if not note_info:
            logger.error("Failed to create weekly summary note")
            return None

        logger.info(f"Successfully created weekly summary: {note_info['url']}")
        note_id = note_info["noteId"]
        note_title = f"Summary of week {week_year}"

        # Save to database (without audio initially)
        save_weekly_summary(
            week_year=week_year,
            year=year,
            week=week,
            title=note_title,
            trilium_note_id=note_id,
        )
        logger.info(f"Saved weekly summary to database: {week_year}")

        # Step 5: Generate TTS audio if enabled
        return _generate_and_attach_tts(note_id, week_year, year, week, note_title)

    except Exception as e:
        logger.error(f"Error in weekly summary generation: {e}", exc_info=True)
        return None
