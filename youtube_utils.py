import subprocess
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

YT_DLP_PATH = "/usr/local/bin/yt-dlp"


def get_video_title(youtube_id: str) -> Optional[str]:
    """
    Fetch the title of a YouTube video using yt-dlp.

    Args:
        youtube_id: YouTube video ID

    Returns:
        The video title if successful, None otherwise
    """
    try:
        url = f"https://www.youtube.com/watch?v={youtube_id}"

        # Use yt-dlp to get video info without downloading
        result = subprocess.run(
            [YT_DLP_PATH, "--dump-json", "--no-playlist", url],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            video_info = json.loads(result.stdout)
            title = video_info.get("title", "Unknown Title")
            logger.info(f"Fetched title for {youtube_id}: {title}")
            return title
        else:
            logger.error(f"yt-dlp failed for {youtube_id}: {result.stderr}")
            return None

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout fetching title for {youtube_id}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse yt-dlp output for {youtube_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching title for {youtube_id}: {e}")
        return None


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
