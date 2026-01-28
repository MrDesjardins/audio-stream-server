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
            # Search for all text notes under the parent note using ETAPI search
            # Using search with ancestorNoteId to get all children
            search_url = f"{config.trilium_url}/etapi/notes"
            params: dict[str, str] = {
                "search": "note.type = text",  # Only get text notes (summaries)
                "ancestorNoteId": config.trilium_parent_note_id,
                "orderBy": "dateModified",
                "limit": str(limit * 2),  # Get more than needed to account for filtering
            }
            response = await client.get(search_url, headers=headers, params=params, timeout=30.0)
            response.raise_for_status()

            # Trilium search returns {"results": [...]}
            response_data = response.json()
            results = response_data.get("results", [])

            if not results or len(results) == 0:
                logger.warning(
                    f"No text notes found under parent note {config.trilium_parent_note_id}"
                )
                return []

            # Process results - they already have title, noteId, and dateModified
            audiobooks = []
            for note in results:
                note_id = note.get("noteId")
                if not note_id:
                    continue

                # Skip the parent note itself if it appears in results
                if note_id == config.trilium_parent_note_id:
                    continue

                audiobooks.append(
                    {
                        "title": note.get("title", "Unknown"),
                        "noteId": note_id,
                        "dateModified": note.get("utcDateModified", ""),
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

Suggest {count} audiobooks that the reader might enjoy. These should be well-known, popular books with full-length audiobooks available on YouTube.

IMPORTANT INSTRUCTIONS:
- Only suggest mainstream, well-known books that definitely have audiobooks on YouTube
- Prefer classic books and bestsellers (e.g., "The 48 Laws of Power", "Atomic Habits", "Think and Grow Rich")
- Only books in similar genres/themes to the list above
- You CANNOT search YouTube or verify URLs - suggest books you're confident have audiobooks available
- DO NOT include YouTube URLs or video IDs - just book titles and authors

Format your response EXACTLY as follows for each suggestion:
TITLE: [Full Book Title]
AUTHOR: [Author Name]
---

Example:
TITLE: Atomic Habits: An Easy & Proven Way to Build Good Habits & Break Bad Ones
AUTHOR: James Clear
---"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a knowledgeable book recommendation assistant. Suggest only well-known books that likely have audiobooks on YouTube.",
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

Suggest {count} audiobooks that the reader might enjoy. These should be well-known, popular books with full-length audiobooks available on YouTube.

IMPORTANT INSTRUCTIONS:
- Only suggest mainstream, well-known books that definitely have audiobooks on YouTube
- Prefer classic books and bestsellers (e.g., "The 48 Laws of Power", "Atomic Habits", "Think and Grow Rich")
- Only books in similar genres/themes to the list above
- You CANNOT search YouTube or verify URLs - suggest books you're confident have audiobooks available
- DO NOT include YouTube URLs or video IDs - just book titles and authors

Format your response EXACTLY as follows for each suggestion:
TITLE: [Full Book Title]
AUTHOR: [Author Name]
---

Example:
TITLE: Atomic Habits: An Easy & Proven Way to Build Good Habits & Break Bad Ones
AUTHOR: James Clear
---"""

        response = model.generate_content(prompt)
        content = response.text

        return parse_suggestions(content)

    except Exception as e:
        logger.error(f"Error generating suggestions with Gemini: {e}", exc_info=True)
        return []


def search_youtube_audiobook(book_title: str, author: str) -> Optional[str]:
    """
    Search YouTube for an audiobook and return the first valid video ID.

    Args:
        book_title: Book title
        author: Author name

    Returns:
        Video ID if found and valid, None otherwise
    """
    from services.youtube import YT_DLP_PATH
    import subprocess
    import json

    try:
        # Search for audiobook on YouTube
        search_query = f"{book_title} {author} audiobook full"
        search_url = f"ytsearch5:{search_query}"

        result = subprocess.run(
            [
                YT_DLP_PATH,
                "--dump-json",
                "--no-playlist",
                "--extractor-args",
                "youtube:player_client=android",
                search_url,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode != 0:
            logger.warning(f"YouTube search failed for '{book_title}': {result.stderr}")
            return None

        # Parse each line of JSON output (one per video)
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            try:
                video_info = json.loads(line)
                video_id = video_info.get("id")
                video_title = video_info.get("title", "")
                duration = video_info.get("duration", 0)

                # Filter: must be at least 30 minutes (1800 seconds) to be a full audiobook
                if duration < 1800:
                    logger.debug(f"Skipping short video: {video_title} ({duration}s)")
                    continue

                # Filter: title should contain "audiobook" or "audio book"
                if (
                    "audiobook" not in video_title.lower()
                    and "audio book" not in video_title.lower()
                ):
                    logger.debug(f"Skipping non-audiobook video: {video_title}")
                    continue

                logger.info(f"Found audiobook: {video_title} ({video_id}, {duration}s)")
                return video_id

            except json.JSONDecodeError:
                continue

        logger.warning(f"No suitable audiobook found for '{book_title} by {author}'")
        return None

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout searching YouTube for '{book_title}'")
        return None
    except Exception as e:
        logger.error(f"Error searching YouTube for '{book_title}': {e}")
        return None


def parse_suggestions(content: str) -> List[Dict[str, str]]:
    """
    Parse AI response into structured suggestions and search YouTube for each.

    Args:
        content: AI response text

    Returns:
        List of dicts with 'title', 'author', 'video_id', and 'youtube_url' keys
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

        # Only add if we have both title and author
        if "title" in suggestion and "author" in suggestion:
            # Search YouTube for the audiobook
            video_id = search_youtube_audiobook(suggestion["title"], suggestion["author"])

            if video_id:
                suggestion["video_id"] = video_id
                suggestion["youtube_url"] = f"https://www.youtube.com/watch?v={video_id}"
                suggestions.append(suggestion)
            else:
                logger.warning(
                    f"Skipping '{suggestion['title']}' - no valid YouTube audiobook found"
                )

    logger.info(f"Parsed {len(suggestions)} valid suggestions with YouTube videos")
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
