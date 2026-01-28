"""
Queue management routes.
"""

import logging
import threading
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from services.database import (
    add_to_queue,
    get_queue,
    get_next_in_queue,
    remove_from_queue,
    clear_queue,
)
from services.youtube import get_video_title, get_video_metadata, extract_video_id
from config import get_config

logger = logging.getLogger(__name__)
router = APIRouter()
config = get_config()


class QueueRequest(BaseModel):
    youtube_video_id: str
    skip_transcription: bool = False


@router.post("/queue/add")
def add_video_to_queue(request: QueueRequest):
    """Add a video to the queue."""
    try:
        video_id = extract_video_id(request.youtube_video_id)
        metadata = get_video_metadata(video_id)

        if metadata:
            queue_id = add_to_queue(
                video_id, metadata["title"], metadata.get("channel"), metadata.get("thumbnail_url")
            )
            video_title = metadata["title"]
        else:
            video_title = f"YouTube Video {video_id}"
            queue_id = add_to_queue(video_id, video_title)

        return JSONResponse(
            {"status": "added", "queue_id": queue_id, "youtube_id": video_id, "title": video_title}
        )
    except Exception as e:
        logger.error(f"Error adding to queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue")
def get_current_queue():
    """Get the current queue."""
    try:
        queue = get_queue()
        return JSONResponse({"queue": queue})
    except Exception as e:
        logger.error(f"Error fetching queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/queue/{queue_id}")
def remove_from_queue_endpoint(queue_id: int):
    """Remove an item from the queue."""
    try:
        success = remove_from_queue(queue_id)
        if success:
            return JSONResponse({"status": "removed", "queue_id": queue_id})
        else:
            raise HTTPException(status_code=404, detail="Queue item not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing from queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/next")
def play_next_in_queue():
    """Remove current item and start playing the next item in queue."""
    try:
        next_item = get_next_in_queue()

        if not next_item:
            return JSONResponse({"status": "queue_empty", "message": "No more items in queue"})

        # Remove the current first item
        remove_from_queue(next_item["id"])

        # Get the new first item (which was second)
        next_item = get_next_in_queue()

        if not next_item:
            return JSONResponse({"status": "queue_empty", "message": "No more items in queue"})

        return JSONResponse(
            {
                "status": "next",
                "youtube_id": next_item["youtube_id"],
                "title": next_item["title"],
                "queue_id": next_item["id"],
            }
        )
    except Exception as e:
        logger.error(f"Error playing next in queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/clear")
def clear_current_queue():
    """Clear all items from the queue."""
    try:
        clear_queue()
        return JSONResponse({"status": "cleared"})
    except Exception as e:
        logger.error(f"Error clearing queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/prefetch/{video_id}")
def prefetch_audio(video_id: str):
    """
    Pre-download audio for a video in the background.
    Called by the frontend when current track is nearing its end,
    so the next track is cached and ready to play immediately.
    """
    from services.streaming import (
        start_youtube_download,
        finish_youtube_download,
        is_download_in_progress,
    )
    from services.cache import get_audio_cache
    import os

    audio_cache = get_audio_cache()
    audio_path = config.get_audio_path(video_id)

    # Already cached — nothing to do
    if audio_cache.check_file_exists(video_id):
        logger.info(f"Prefetch {video_id}: already cached")
        return JSONResponse({"status": "cached", "video_id": video_id})

    # Already downloading — don't start a second one
    if is_download_in_progress(video_id):
        logger.info(f"Prefetch {video_id}: download already in progress")
        return JSONResponse({"status": "downloading", "video_id": video_id})

    # Start background download (fire and forget)
    proc, _ = start_youtube_download(video_id, skip_transcription=True)

    if proc is None:
        return JSONResponse({"status": "cached", "video_id": video_id})

    def _prefetch_worker():
        proc.wait()
        finish_youtube_download(video_id, proc.returncode)

    thread = threading.Thread(target=_prefetch_worker, daemon=True)
    thread.start()

    logger.info(f"Prefetch {video_id}: started background download")
    return JSONResponse({"status": "started", "video_id": video_id})


@router.post("/queue/suggestions")
async def generate_and_queue_suggestions():
    """
    Generate audiobook suggestions based on recent books from Trilium
    and automatically add them to the queue.
    """
    if not config.book_suggestions_enabled:
        raise HTTPException(
            status_code=400,
            detail="Book suggestions feature is disabled. Set BOOK_SUGGESTIONS_ENABLED=true in .env",
        )

    try:
        from services.book_suggestions import get_audiobook_suggestions

        logger.info("Generating audiobook suggestions from Trilium books...")

        # Get suggestions
        suggestions = await get_audiobook_suggestions()

        if not suggestions:
            return JSONResponse(
                {
                    "status": "no_suggestions",
                    "message": "No suggestions could be generated. Check logs for details.",
                    "added": [],
                }
            )

        # Add suggestions to queue
        added = []
        failed = []

        for suggestion in suggestions:
            try:
                video_id = suggestion["video_id"]

                # Try to get metadata from YouTube (validate the URL)
                metadata = get_video_metadata(video_id)

                if metadata:
                    queue_id = add_to_queue(
                        video_id,
                        metadata["title"],
                        metadata.get("channel"),
                        metadata.get("thumbnail_url"),
                    )
                    added.append(
                        {
                            "queue_id": queue_id,
                            "video_id": video_id,
                            "title": metadata["title"],
                            "suggested_title": suggestion["title"],
                            "author": suggestion.get("author", "Unknown"),
                        }
                    )
                    logger.info(f"Added suggestion to queue: {metadata['title']}")
                else:
                    # Fall back to AI-provided title
                    queue_id = add_to_queue(
                        video_id, f"{suggestion['title']} by {suggestion.get('author', 'Unknown')}"
                    )
                    added.append(
                        {
                            "queue_id": queue_id,
                            "video_id": video_id,
                            "title": suggestion["title"],
                            "author": suggestion.get("author", "Unknown"),
                        }
                    )
                    logger.warning(
                        f"Could not fetch YouTube metadata for {video_id}, using AI title"
                    )

            except Exception as e:
                logger.error(f"Failed to add suggestion to queue: {e}")
                failed.append({"title": suggestion.get("title", "Unknown"), "error": str(e)})

        return JSONResponse(
            {
                "status": "success",
                "message": f"Added {len(added)} audiobook suggestions to queue",
                "added": added,
                "failed": failed,
                "total_suggestions": len(suggestions),
            }
        )

    except Exception as e:
        logger.error(f"Error generating suggestions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate suggestions: {str(e)}")
