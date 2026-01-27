"""
Book-based audiobook suggestion service.

Analyzes recent books from Trilium and suggests YouTube audiobooks using AI.
"""

import logging
import re
from typing import List, Dict, Optional
import httpx
from openai import OpenAI
from config import get_config

logger = logging.getLogger(__name__)
config = get_config()


async def get_recent_books_from_trilium(limit: int) -> List[Dict[str, str]]:
    """
    Fetch recent audiobook summaries from Trilium parent note's children.

    Args:
        limit: Maximum number of audiobooks to fetch

    Returns:
        List of dicts with 'title' and 'noteId' keys
    """
    try:
        headers = {"Authorization": config.trilium_etapi_token, "Content-Type": "application/json"}

        logger.info(f"Fetching children of parent note: {config.trilium_parent_note_id}")

        async with httpx.AsyncClient() as client:
            # Get all immediate children of the parent note
            children_url = (
                f"{config.trilium_url}/etapi/notes/{config.trilium_parent_note_id}/children"
            )
            response = await client.get(children_url, headers=headers, timeout=30.0)
            response.raise_for_status()

            children = response.json()

            if not children:
                logger.warning(
                    f"No children found under parent note {config.trilium_parent_note_id}"
                )
                return []

            # Fetch details for each child to get dateModified
            audiobooks = []
            for child in children:
                note_id = child.get("noteId")
                if not note_id:
                    continue

                # Get full note details
                note_url = f"{config.trilium_url}/etapi/notes/{note_id}"
                note_response = await client.get(note_url, headers=headers, timeout=10.0)

                if note_response.status_code == 200:
                    note_data = note_response.json()

                    # Only include text notes (summaries)
                    if note_data.get("type") == "text":
                        audiobooks.append(
                            {
                                "title": note_data.get("title", "Unknown"),
                                "noteId": note_id,
                                "dateModified": note_data.get("dateModified", ""),
                            }
                        )

            # Sort by dateModified descending (most recent first) and take the limit
            audiobooks.sort(key=lambda x: x.get("dateModified", ""), reverse=True)
            audiobooks = audiobooks[:limit]

            logger.info(f"Found {len(audiobooks)} recent audiobook summaries in Trilium")

            # Log the titles for debugging
            if audiobooks:
                titles_preview = ", ".join([ab["title"][:50] for ab in audiobooks[:3]])
                logger.info(f"Most recent: {titles_preview}...")

            return audiobooks

    except Exception as e:
        logger.error(f"Error fetching audiobooks from Trilium: {e}", exc_info=True)
        return []


def generate_suggestions_openai(book_titles: List[str], count: int) -> List[Dict[str, str]]:
    """
    Generate audiobook suggestions using OpenAI.

    Args:
        book_titles: List of book titles to base suggestions on
        count: Number of suggestions to generate

    Returns:
        List of dicts with 'title', 'author', and 'youtube_url' keys
    """
    try:
        client = OpenAI(api_key=config.openai_api_key)

        books_text = "\n".join(f"- {title}" for title in book_titles)

        prompt = f"""Based on these recently read books:
{books_text}

Suggest {count} audiobooks that the reader might enjoy. For each suggestion:
1. Find a similar book (same genre, author, or theme)
2. Search for its audiobook on YouTube
3. Provide a real, working YouTube URL

Format your response EXACTLY as follows for each suggestion:
TITLE: [Book Title]
AUTHOR: [Author Name]
URL: https://www.youtube.com/watch?v=[VIDEO_ID]
---

Make sure each URL is a real, working YouTube audiobook link. Verify that the video ID is valid."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a knowledgeable book recommendation assistant with access to YouTube audiobooks. Always provide real, working YouTube URLs.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=1000,
        )

        content = response.choices[0].message.content
        return parse_suggestions(content)

    except Exception as e:
        logger.error(f"Error generating suggestions with OpenAI: {e}", exc_info=True)
        return []


def generate_suggestions_gemini(book_titles: List[str], count: int) -> List[Dict[str, str]]:
    """
    Generate audiobook suggestions using Google Gemini.

    Args:
        book_titles: List of book titles to base suggestions on
        count: Number of suggestions to generate

    Returns:
        List of dicts with 'title', 'author', and 'youtube_url' keys
    """
    try:
        import google.generativeai as genai

        genai.configure(api_key=config.gemini_api_key)
        model = genai.GenerativeModel("gemini-2.0-flash-exp")

        books_text = "\n".join(f"- {title}" for title in book_titles)

        prompt = f"""Based on these recently read books:
{books_text}

Suggest {count} audiobooks that the reader might enjoy. For each suggestion:
1. Find a similar book (same genre, author, or theme)
2. Search for its audiobook on YouTube
3. Provide a real, working YouTube URL

Format your response EXACTLY as follows for each suggestion:
TITLE: [Book Title]
AUTHOR: [Author Name]
URL: https://www.youtube.com/watch?v=[VIDEO_ID]
---

Make sure each URL is a real, working YouTube audiobook link. Verify that the video ID is valid."""

        response = model.generate_content(prompt)
        content = response.text

        return parse_suggestions(content)

    except Exception as e:
        logger.error(f"Error generating suggestions with Gemini: {e}", exc_info=True)
        return []


def parse_suggestions(content: str) -> List[Dict[str, str]]:
    """
    Parse AI response into structured suggestions.

    Args:
        content: AI response text

    Returns:
        List of dicts with 'title', 'author', and 'youtube_url' keys
    """
    suggestions = []

    # Split by --- separator
    blocks = content.split("---")

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        suggestion = {}

        # Extract title
        title_match = re.search(r"TITLE:\s*(.+)", block, re.IGNORECASE)
        if title_match:
            suggestion["title"] = title_match.group(1).strip()

        # Extract author
        author_match = re.search(r"AUTHOR:\s*(.+)", block, re.IGNORECASE)
        if author_match:
            suggestion["author"] = author_match.group(1).strip()

        # Extract YouTube URL and video ID
        url_match = re.search(
            r"URL:\s*(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]+))",
            block,
            re.IGNORECASE,
        )
        if url_match:
            full_url = url_match.group(1).strip()
            video_id = url_match.group(2).strip()

            # Video IDs are typically 11 characters, but extract the first 11
            if len(video_id) >= 11:
                video_id = video_id[:11]

            suggestion["youtube_url"] = full_url
            suggestion["video_id"] = video_id

        # Only add if we have all required fields
        if "title" in suggestion and "youtube_url" in suggestion and "video_id" in suggestion:
            suggestions.append(suggestion)

    logger.info(f"Parsed {len(suggestions)} valid suggestions from AI response")
    return suggestions


async def filter_already_played(suggestions: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Filter out suggestions that have already been played.

    Args:
        suggestions: List of suggestion dicts with 'video_id' key

    Returns:
        Filtered list of suggestions
    """
    from services.database import get_history

    try:
        # Get play history
        history = get_history(limit=1000)  # Get more history to check against
        played_video_ids = {item["youtube_id"] for item in history}

        # Filter out already played
        filtered = [s for s in suggestions if s.get("video_id") not in played_video_ids]

        removed_count = len(suggestions) - len(filtered)
        if removed_count > 0:
            logger.info(f"Filtered out {removed_count} already-played suggestions")

        return filtered

    except Exception as e:
        logger.error(f"Error filtering suggestions: {e}", exc_info=True)
        return suggestions  # Return unfiltered on error


async def get_audiobook_suggestions() -> List[Dict[str, str]]:
    """
    Get audiobook suggestions based on recent books from Trilium.

    Returns:
        List of suggestion dicts with 'title', 'author', 'youtube_url', 'video_id' keys
    """
    if not config.book_suggestions_enabled:
        logger.warning("Book suggestions feature is disabled")
        return []

    # Step 1: Get recent books from Trilium
    books = await get_recent_books_from_trilium(config.books_to_analyze)

    if not books:
        logger.warning("No recent books found in Trilium")
        return []

    book_titles = [book["title"] for book in books]
    logger.info(f"Analyzing {len(book_titles)} recent books: {', '.join(book_titles[:3])}...")

    # Step 2: Generate suggestions using AI
    if config.suggestions_ai_provider == "openai":
        suggestions = generate_suggestions_openai(book_titles, config.suggestions_count)
    elif config.suggestions_ai_provider == "gemini":
        suggestions = generate_suggestions_gemini(book_titles, config.suggestions_count)
    else:
        logger.error(f"Invalid AI provider: {config.suggestions_ai_provider}")
        return []

    if not suggestions:
        logger.warning("No suggestions generated by AI")
        return []

    # Step 3: Filter out already played audiobooks
    filtered_suggestions = await filter_already_played(suggestions)

    logger.info(f"Generated {len(filtered_suggestions)} new audiobook suggestions")
    return filtered_suggestions
