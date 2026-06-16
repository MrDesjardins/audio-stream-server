"""
Queue management routes.
"""

import asyncio
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from services.audio_prefetch import (
    enqueue_audio_prefetch,
    get_audio_prefetch_status,
)
from services.database import (
    add_to_queue,
    get_queue,
    get_next_in_queue,
    get_queue_item_by_id,
    get_next_in_queue_after_position,
    remove_from_queue,
    clear_queue,
    reorder_queue,
)
from services.youtube import get_video_metadata, extract_video_id
from config import get_config

logger = logging.getLogger(__name__)
router = APIRouter()
config = get_config()


class QueueRequest(BaseModel):
    youtube_video_id: str
    skip_transcription: bool = False


class ReorderRequest(BaseModel):
    queue_item_ids: List[int]


class PlayNextRequest(BaseModel):
    queue_id: Optional[int] = None


def _queue_item_to_response(item) -> dict:
    """Convert a queue item to API response data with audio readiness."""
    data = item.to_dict()
    if (item.type or "youtube") == "youtube":
        data["audio_status"] = get_audio_prefetch_status(item.youtube_id)
    return data


def get_queue_audio_status_hash() -> int:
    """Return a cheap hash for current YouTube queue audio readiness."""
    try:
        queue = get_queue()
    except Exception as e:
        logger.warning("Failed to compute queue audio status hash: %s", e)
        return 0

    status_value = 0
    for item in queue:
        if (item.type or "youtube") != "youtube":
            continue
        status = get_audio_prefetch_status(item.youtube_id)
        status_value = (
            (status_value * 131) + (item.id * 17) + sum(ord(char) for char in status)
        )
    return status_value


def _enqueue_prefetch_safely(video_id: str) -> None:
    """Start warming audio without failing the queue operation."""
    try:
        status = enqueue_audio_prefetch(video_id)
        logger.info("Prefetch enqueue for %s returned %s", video_id, status)
    except Exception as e:
        logger.warning("Failed to enqueue prefetch for %s: %s", video_id, e)


@router.post("/queue/add")
def add_video_to_queue(request: QueueRequest) -> JSONResponse:
    """Add a video to the queue."""
    try:
        video_id = extract_video_id(request.youtube_video_id)
        metadata = get_video_metadata(video_id)

        if metadata:
            queue_id = add_to_queue(
                video_id,
                metadata["title"],
                metadata.get("channel"),
                metadata.get("thumbnail_url"),
            )
            video_title = metadata["title"]
        else:
            video_title = f"YouTube Video {video_id}"
            queue_id = add_to_queue(video_id, video_title)

        _enqueue_prefetch_safely(video_id)

        return JSONResponse(
            {
                "status": "added",
                "queue_id": queue_id,
                "youtube_id": video_id,
                "title": video_title,
            }
        )
    except Exception as e:
        logger.error(f"Error adding to queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue")
def get_current_queue() -> JSONResponse:
    """Get the current queue."""
    try:
        queue = get_queue()
        return JSONResponse(
            {"queue": [_queue_item_to_response(item) for item in queue]}
        )
    except Exception as e:
        logger.error(f"Error fetching queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/queue/{queue_id}")
def remove_from_queue_endpoint(queue_id: int) -> JSONResponse:
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
def play_next_in_queue(request: PlayNextRequest = PlayNextRequest()) -> JSONResponse:
    """Remove the completed/skipped item and return the next item in queue order."""
    try:
        if request.queue_id is not None:
            current_item = get_queue_item_by_id(request.queue_id)
        else:
            current_item = get_next_in_queue()

        if not current_item:
            return JSONResponse(
                {"status": "queue_empty", "message": "No more items in queue"}
            )

        removed_position = current_item.position
        remove_from_queue(current_item.id)

        next_item = get_next_in_queue_after_position(removed_position)

        if not next_item:
            return JSONResponse(
                {"status": "queue_empty", "message": "No more items in queue"}
            )

        # Build response based on type
        response = {
            "status": "next",
            "title": next_item.title,
            "queue_id": next_item.id,
            "type": next_item.type,
        }

        # Add type-specific fields
        if next_item.type == "summary":
            response["week_year"] = next_item.week_year
        else:
            response["youtube_id"] = next_item.youtube_id

        return JSONResponse(response)
    except Exception as e:
        logger.error(f"Error playing next in queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/clear")
def clear_current_queue() -> JSONResponse:
    """Clear all items from the queue."""
    try:
        clear_queue()
        return JSONResponse({"status": "cleared"})
    except Exception as e:
        logger.error(f"Error clearing queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/reorder")
def reorder_queue_endpoint(request: ReorderRequest) -> JSONResponse:
    """
    Reorder queue items by updating their positions.

    Request body should contain a list of queue item IDs in the desired order.
    """
    try:
        success = reorder_queue(request.queue_item_ids)
        if success:
            return JSONResponse(
                {"status": "reordered", "count": len(request.queue_item_ids)}
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to reorder queue")
    except Exception as e:
        logger.error(f"Error reordering queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/prefetch/{video_id}")
def prefetch_audio(video_id: str) -> JSONResponse:
    """
    Pre-download audio for a video in the background.
    Called by the frontend when current track is nearing its end,
    so the next track is cached and ready to play immediately.
    """
    status = enqueue_audio_prefetch(video_id)
    return JSONResponse({"status": status, "video_id": video_id})


def _run_suggestions_sync() -> dict:
    """
    Run the entire suggestion pipeline synchronously.

    This is designed to be called via asyncio.to_thread() so it doesn't
    block the event loop. All operations here (LLM calls, subprocess calls,
    database writes) are synchronous.
    """
    from services.book_suggestions import get_video_suggestions

    logger.info("Generating video suggestions based on recently watched content...")

    suggestions = get_video_suggestions()

    if not suggestions:
        return {
            "status": "no_suggestions",
            "message": "No suggestions could be generated. Check logs for details.",
            "added": [],
        }

    added = []
    failed = []

    for suggestion in suggestions:
        try:
            video_id = suggestion["video_id"]
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
                        "channel": suggestion.get("channel", "Unknown"),
                    }
                )
                _enqueue_prefetch_safely(video_id)
                logger.info(f"Added suggestion to queue: {metadata['title']}")
            else:
                queue_id = add_to_queue(
                    video_id,
                    suggestion["title"],
                    suggestion.get("channel"),
                )
                added.append(
                    {
                        "queue_id": queue_id,
                        "video_id": video_id,
                        "title": suggestion["title"],
                        "channel": suggestion.get("channel", "Unknown"),
                    }
                )
                _enqueue_prefetch_safely(video_id)
                logger.warning(
                    f"Could not fetch YouTube metadata for {video_id}, using search result"
                )

        except Exception as e:
            logger.error(f"Failed to add suggestion to queue: {e}")
            failed.append(
                {"title": suggestion.get("title", "Unknown"), "error": str(e)}
            )

    return {
        "status": "success",
        "message": f"Added {len(added)} video suggestions to queue",
        "added": added,
        "failed": failed,
        "total_suggestions": len(suggestions),
    }


@router.post("/queue/suggestions")
async def generate_and_queue_suggestions() -> JSONResponse:
    """
    Generate video suggestions based on recently watched content
    and automatically add them to the queue.

    Runs the blocking suggestion pipeline in a thread so the event loop
    stays free to handle other requests (queue removal, playback, etc.).
    """
    if not config.book_suggestions_enabled:
        raise HTTPException(
            status_code=400,
            detail="Video suggestions feature is disabled. Set BOOK_SUGGESTIONS_ENABLED=true in .env",
        )

    try:
        result = await asyncio.to_thread(_run_suggestions_sync)
        return JSONResponse(result)

    except Exception as e:
        logger.error(f"Error generating suggestions: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to generate suggestions: {str(e)}"
        )
