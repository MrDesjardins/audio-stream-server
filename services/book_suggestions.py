"""
YouTube video suggestion service based on recently watched content.

Analyzes summaries from recent videos and suggests similar YouTube content.
"""

import logging
import json
import subprocess
from typing import List, Dict, Optional

from config import get_config
from services.llm_clients import get_tracked_openai_client, get_tracked_gemini_client
from services.database import get_history
from services.models import VideoSummary, PlayHistoryItem

logger = logging.getLogger(__name__)
config = get_config()


def _extract_text_from_html(html_content: str) -> str:
    """
    Extract plain text from HTML content.

    Args:
        html_content: HTML content string

    Returns:
        Plain text with HTML tags removed
    """
    import re

    # Remove the YouTube link section at the bottom
    content = re.sub(r'<p style="margin-top.*?</p>', "", html_content, flags=re.DOTALL)

    # Strip HTML tags to get plain text
    text = re.sub(r"<[^>]+>", " ", content)

    # Clean up whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def _fetch_summary_for_video(item: PlayHistoryItem) -> Optional[VideoSummary]:
    """
    Fetch summary for a single video from Trilium.

    Args:
        item: PlayHistoryItem to fetch summary for

    Returns:
        VideoSummary object if found, None otherwise
    """
    from services.trilium import check_video_exists, get_note_content

    video_id = item.youtube_id
    title = item.title

    # Check if Trilium note exists for this video
    note_info = check_video_exists(video_id)

    if not note_info:
        logger.debug(f"No Trilium note found for {title}")
        return None

    note_id = note_info["noteId"]
    logger.debug(f"Found Trilium note for {title}: {note_id}")

    # Fetch note content
    content = get_note_content(note_id)

    if not content:
        logger.debug(f"Could not fetch note content for {title}")
        return None

    # Extract summary from HTML content
    text_summary = _extract_text_from_html(content)

    if not text_summary:
        return None

    logger.debug(f"Extracted summary for {title} ({len(text_summary)} chars)")

    return VideoSummary(
        video_id=video_id,
        title=title,
        summary=text_summary,
        note_url=note_info.get("url"),
    )


async def get_recent_summaries(limit: int) -> List[VideoSummary]:
    """
    Get summaries from recently watched videos (fetched from Trilium).

    Args:
        limit: Maximum number of summaries to fetch

    Returns:
        List of VideoSummary objects
    """
    try:
        # Get recent history (get more to account for videos without summaries)
        history = get_history(limit=limit * 2)

        if not history:
            logger.warning("No history found")
            return []

        summaries: List[VideoSummary] = []

        for item in history:
            summary = _fetch_summary_for_video(item)
            if summary:
                summaries.append(summary)

                # Stop when we have enough
                if len(summaries) >= limit:
                    break

        logger.info(f"Found {len(summaries)} summaries from recent history")
        return summaries

    except Exception as e:
        logger.error(f"Error getting recent summaries: {e}", exc_info=True)
        return []


def _build_theme_prompt(summaries: List[VideoSummary]) -> str:
    """
    Build the prompt for theme generation.

    Args:
        summaries: List of VideoSummary objects

    Returns:
        Formatted prompt string
    """
    summaries_text = "\n\n".join(
        f"Video {i + 1}:\n{s.summary}" for i, s in enumerate(summaries)
    )

    return f"""Analyze these video summaries from recently watched content:

{summaries_text}

Based on the themes, topics, and interests shown in these videos, write ONE sentence that captures the overarching theme or interest area. This will be used to search YouTube for similar content.

The sentence should be:
- Descriptive and specific (not generic)
- Does not contain specific names as it needs to be general
- Focus on the key topics/themes that appear across multiple videos
- Suitable for use as a YouTube search query

Respond with ONLY the theme sentence, nothing else."""


def generate_theme_openai(summaries: List[VideoSummary]) -> Optional[str]:
    """
    Generate a 1-sentence theme from summaries using OpenAI.

    Args:
        summaries: List of dicts with 'summary' key

    Returns:
        A 1-sentence theme string, or None on error
    """
    try:
        config = get_config()
        client = get_tracked_openai_client()

        prompt = _build_theme_prompt(summaries)

        messages = [
            {
                "role": "system",
                "content": "You are an expert at identifying themes and patterns in content consumption.",
            },
            {"role": "user", "content": prompt},
        ]

        metadata = {"summaries_count": len(summaries)}

        response = client.create_chat_completion(
            messages=messages,
            feature="book_suggestions",
            metadata=metadata,
            temperature=0.9,
            max_tokens=500,
            model_override=config.suggestions_model,
        )

        theme = response.choices[0].message.content
        theme = theme.strip() if theme else None
        logger.info(f"Generated theme: {theme}")

        return theme

    except Exception as e:
        logger.error(f"Error generating theme with OpenAI: {e}", exc_info=True)
        return None


def generate_theme_gemini(summaries: List[VideoSummary]) -> Optional[str]:
    """
    Generate a 1-sentence theme from summaries using Gemini.

    Args:
        summaries: List of VideoSummary objects

    Returns:
        A 1-sentence theme string, or None on error
    """
    try:
        config = get_config()
        client = get_tracked_gemini_client()

        prompt = _build_theme_prompt(summaries)

        metadata = {"summaries_count": len(summaries)}

        response = client.generate_content(
            prompt=prompt,
            feature="book_suggestions",
            metadata=metadata,
            model_override=config.suggestions_model,
        )

        theme = response.text
        theme = theme.strip() if theme else None
        logger.info(f"Generated theme: {theme}")

        return theme

    except Exception as e:
        logger.error(f"Error generating theme with Gemini: {e}", exc_info=True)
        return None


def _parse_video_json_line(line: str) -> Optional[Dict[str, str]]:
    """
    Parse a single line of yt-dlp JSON output.

    Args:
        line: JSON line from yt-dlp output

    Returns:
        Dict with video info if valid and meets duration requirement, None otherwise
    """
    if not line:
        return None

    try:
        video_info = json.loads(line)
        video_id = video_info.get("id")
        title = video_info.get("title", "")
        channel = video_info.get("uploader", "Unknown")
        duration = video_info.get("duration", 0)

        # Filter: must be at least 10 minutes (600 seconds)
        if duration < 600:
            logger.debug(f"Skipping short video: {title} ({duration}s)")
            return None

        logger.info(f"Found video: {title} ({video_id}, {duration}s)")
        return {
            "video_id": video_id,
            "title": title,
            "channel": channel,
            "duration": duration,
            "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
        }

    except json.JSONDecodeError:
        return None


def search_youtube_by_theme(theme: str, count: int) -> List[Dict[str, str]]:
    """
    Search YouTube for videos matching the theme.

    Args:
        theme: Search query theme
        count: Number of videos to find

    Returns:
        List of dicts with 'video_id', 'title', 'channel', 'duration', 'youtube_url' keys
    """
    from services.youtube import YT_DLP_PATH

    try:
        # Search YouTube using the theme
        search_url = (
            f"ytsearch{count * 2}:{theme}"  # Get more than needed for filtering
        )
        logger.info(f"Searching YouTube for theme: {theme}")
        logger.debug(f"YT-DLP search URL: {search_url}")
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
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning(
                f"YouTube search failed for theme '{theme}': {result.stderr}"
            )
            return []

        videos = []

        # Parse each line of JSON output (one per video)
        for line in result.stdout.strip().split("\n"):
            video = _parse_video_json_line(line)
            if video:
                videos.append(video)

                # Stop when we have enough
                if len(videos) >= count:
                    break

        logger.info(f"Found {len(videos)} videos for theme: {theme}")
        return videos

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout searching YouTube for theme '{theme}'")
        return []
    except Exception as e:
        logger.error(f"Error searching YouTube for theme '{theme}': {e}")
        return []


async def filter_already_played(videos: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Filter out videos that have already been played.

    Args:
        videos: List of video dicts with 'video_id' key

    Returns:
        Filtered list of videos
    """
    try:
        # Get play history
        history = get_history(limit=1000)  # Get more history to check against
        played_video_ids = {item.youtube_id for item in history}

        # Filter out already played
        filtered = [v for v in videos if v.get("video_id") not in played_video_ids]

        removed_count = len(videos) - len(filtered)
        if removed_count > 0:
            logger.info(f"Filtered out {removed_count} already-played videos")

        return filtered

    except Exception as e:
        logger.error(f"Error filtering videos: {e}", exc_info=True)
        return videos  # Return unfiltered on error


async def get_video_suggestions() -> List[Dict[str, str]]:
    """
    Get video suggestions based on recently watched content.

    Workflow:
    1. Get summaries from last BOOKS_TO_ANALYZE videos
    2. Generate a 1-sentence theme using AI
    3. Search YouTube for videos matching the theme
    4. Filter out already-watched videos
    5. Return suggestions

    Returns:
        List of suggestion dicts with 'video_id', 'title', 'channel', 'youtube_url' keys
    """
    if not config.book_suggestions_enabled:
        logger.warning("Video suggestions feature is disabled")
        return []

    # Step 1: Get recent summaries
    summaries = await get_recent_summaries(config.books_to_analyze)

    if not summaries:
        logger.warning("No summaries found from recent videos")
        return []

    logger.info(f"Analyzing {len(summaries)} recent video summaries")

    # Step 2: Generate theme from summaries
    if config.suggestions_ai_provider == "openai":
        theme = generate_theme_openai(summaries)
    elif config.suggestions_ai_provider == "gemini":
        theme = generate_theme_gemini(summaries)
    else:
        logger.error(f"Invalid AI provider: {config.suggestions_ai_provider}")
        return []

    if not theme:
        logger.warning("Failed to generate theme from summaries")
        return []

    logger.info(f"Generated theme: '{theme}'")

    # Step 3: Search YouTube for videos matching the theme
    videos = search_youtube_by_theme(theme, config.suggestions_count)

    if not videos:
        logger.warning("No videos found for the generated theme")
        return []

    # Step 4: Filter out already played videos
    filtered_videos = await filter_already_played(videos)

    logger.info(f"Generated {len(filtered_videos)} new video suggestions")
    return filtered_videos
