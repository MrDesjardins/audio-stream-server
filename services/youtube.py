import subprocess
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

YT_DLP_PATH = "/usr/local/bin/yt-dlp"


def get_video_metadata(youtube_id: str) -> Optional[dict]:
    """
    Fetch metadata for a YouTube video using yt-dlp.

    Args:
        youtube_id: YouTube video ID

    Returns:
        Dictionary with title, channel, and thumbnail_url if successful, None otherwise
    """
    try:
        url = f"https://www.youtube.com/watch?v={youtube_id}"

        # Use yt-dlp to get video info without downloading
        # Use android player client to avoid JS runtime requirement
        result = subprocess.run(
            [
                YT_DLP_PATH,
                "--dump-json",
                "--no-playlist",
                "--extractor-args",
                "youtube:player_client=android",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            video_info = json.loads(result.stdout)

            # Extract title
            title = video_info.get("title", "Unknown Title")

            # Extract channel name (try multiple fields)
            channel = (
                video_info.get("channel")
                or video_info.get("uploader")
                or video_info.get("creator")
                or "Unknown Channel"
            )

            # YouTube thumbnail URL
            # Use standard YouTube thumbnail URLs (always available)
            # Try maxresdefault (1280x720) first, but it's not always available
            # More reliable: hqdefault (480x360) or sddefault (640x480)
            thumbnail_url = f"https://i.ytimg.com/vi/{youtube_id}/hqdefault.jpg"

            metadata = {"title": title, "channel": channel, "thumbnail_url": thumbnail_url}

            logger.info(f"Fetched metadata for {youtube_id}: {title} by {channel}")
            return metadata
        else:
            logger.error(f"yt-dlp failed for {youtube_id}: {result.stderr}")
            return None

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout fetching metadata for {youtube_id}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse yt-dlp output for {youtube_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching metadata for {youtube_id}: {e}")
        return None


def get_video_title(youtube_id: str) -> Optional[str]:
    """
    Fetch the title of a YouTube video using yt-dlp.

    This is a compatibility wrapper around get_video_metadata.

    Args:
        youtube_id: YouTube video ID

    Returns:
        The video title if successful, None otherwise
    """
    metadata = get_video_metadata(youtube_id)
    return metadata["title"] if metadata else None


def extract_video_id(url_or_id: str) -> str:
    """
    Extract video ID from a YouTube URL or return the ID if already an ID.

    Args:
        url_or_id: YouTube URL or video ID

    Returns:
        The video ID
    """
    from urllib.parse import urlparse, parse_qs

    # If it doesn't look like a URL, assume it's already an ID
    if not url_or_id.startswith("http"):
        return url_or_id

    parsed = urlparse(url_or_id)

    # Handle youtu.be short URLs
    if parsed.hostname == "youtu.be":
        return parsed.path.lstrip("/").split("?")[0]

    # Handle youtube.com URLs
    if parsed.hostname in ["www.youtube.com", "youtube.com", "m.youtube.com"]:
        if parsed.path == "/watch":
            query_params = parse_qs(parsed.query)
            return query_params.get("v", [url_or_id])[0]
        elif parsed.path.startswith("/embed/"):
            return parsed.path.split("/embed/")[1].split("?")[0]
        elif parsed.path.startswith("/v/"):
            return parsed.path.split("/v/")[1].split("?")[0]

    # If we can't parse it, return as-is
    return url_or_id
