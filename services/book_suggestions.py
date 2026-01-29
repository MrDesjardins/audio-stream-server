"""
YouTube video suggestion service based on recently watched content.

Analyzes summaries from recent videos and suggests similar YouTube content.
"""

import logging
import json
import subprocess
from typing import List, Dict, Optional
from openai import OpenAI
from google import genai
from config import get_config
from services.cache import get_transcript_cache
from services.database import get_history

logger = logging.getLogger(__name__)
config = get_config()


async def get_recent_summaries(limit: int) -> List[Dict[str, str]]:
    """
    Get summaries from recently watched videos.

    Args:
        limit: Maximum number of summaries to fetch

    Returns:
        List of dicts with 'video_id', 'title', and 'summary' keys
    """
    try:
        # Get recent history
        history = get_history(limit=limit)

        if not history:
            logger.warning("No history found")
            return []

        cache = get_transcript_cache()
        summaries = []

        for item in history:
            video_id = item["youtube_id"]
            title = item["title"]

            # Try to get cached summary
            cached = cache.get_cached(video_id)

            if cached and cached.get("summary"):
                summaries.append({
                    "video_id": video_id,
                    "title": title,
                    "summary": cached["summary"]
                })
                logger.debug(f"Found summary for {title}")
            else:
                logger.debug(f"No summary cached for {title}")

        logger.info(f"Found {len(summaries)} summaries from recent history")
        return summaries

    except Exception as e:
        logger.error(f"Error getting recent summaries: {e}", exc_info=True)
        return []


def generate_theme_openai(summaries: List[Dict[str, str]]) -> Optional[str]:
    """
    Generate a 1-sentence theme from summaries using OpenAI.

    Args:
        summaries: List of dicts with 'summary' key

    Returns:
        A 1-sentence theme string, or None on error
    """
    try:
        client = OpenAI(api_key=config.openai_api_key)

        summaries_text = "\n\n".join(
            f"Video {i+1}:\n{s['summary']}"
            for i, s in enumerate(summaries)
        )

        prompt = f"""Analyze these video summaries from recently watched content:

{summaries_text}

Based on the themes, topics, and interests shown in these videos, write ONE sentence that captures the overarching theme or interest area. This will be used to search YouTube for similar content.

The sentence should be:
- Descriptive and specific (not generic)
- Focus on the key topics/themes that appear across multiple videos
- Suitable for use as a YouTube search query

Respond with ONLY the theme sentence, nothing else."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert at identifying themes and patterns in content consumption.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=100,
        )

        theme = response.choices[0].message.content.strip()
        logger.info(f"Generated theme: {theme}")
        return theme

    except Exception as e:
        logger.error(f"Error generating theme with OpenAI: {e}", exc_info=True)
        return None


def generate_theme_gemini(summaries: List[Dict[str, str]]) -> Optional[str]:
    """
    Generate a 1-sentence theme from summaries using Gemini.

    Args:
        summaries: List of dicts with 'summary' key

    Returns:
        A 1-sentence theme string, or None on error
    """
    try:
        client = genai.Client(api_key=config.gemini_api_key)

        summaries_text = "\n\n".join(
            f"Video {i+1}:\n{s['summary']}"
            for i, s in enumerate(summaries)
        )

        prompt = f"""Analyze these video summaries from recently watched content:

{summaries_text}

Based on the themes, topics, and interests shown in these videos, write ONE sentence that captures the overarching theme or interest area. This will be used to search YouTube for similar content.

The sentence should be:
- Descriptive and specific (not generic)
- Focus on the key topics/themes that appear across multiple videos
- Suitable for use as a YouTube search query

Respond with ONLY the theme sentence, nothing else."""

        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )

        theme = response.text.strip()
        logger.info(f"Generated theme: {theme}")
        return theme

    except Exception as e:
        logger.error(f"Error generating theme with Gemini: {e}", exc_info=True)
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
        search_url = f"ytsearch{count * 2}:{theme}"  # Get more than needed for filtering
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
            logger.warning(f"YouTube search failed for theme '{theme}': {result.stderr}")
            return []

        videos = []

        # Parse each line of JSON output (one per video)
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            try:
                video_info = json.loads(line)
                video_id = video_info.get("id")
                title = video_info.get("title", "")
                channel = video_info.get("uploader", "Unknown")
                duration = video_info.get("duration", 0)

                # Filter: must be at least 10 minutes (600 seconds)
                if duration < 600:
                    logger.debug(f"Skipping short video: {title} ({duration}s)")
                    continue

                videos.append({
                    "video_id": video_id,
                    "title": title,
                    "channel": channel,
                    "duration": duration,
                    "youtube_url": f"https://www.youtube.com/watch?v={video_id}"
                })

                logger.info(f"Found video: {title} ({video_id}, {duration}s)")

                # Stop when we have enough
                if len(videos) >= count:
                    break

            except json.JSONDecodeError:
                continue

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
        played_video_ids = {item["youtube_id"] for item in history}

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


# Backwards compatibility alias
async def get_audiobook_suggestions() -> List[Dict[str, str]]:
    """
    Deprecated: Use get_video_suggestions() instead.

    This function is kept for backwards compatibility.
    """
    return await get_video_suggestions()
