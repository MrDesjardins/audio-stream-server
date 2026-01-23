"""
Queue management routes.
"""
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from services.database import add_to_queue, get_queue, get_next_in_queue, remove_from_queue, clear_queue
from services.youtube import get_video_title, extract_video_id

logger = logging.getLogger(__name__)
router = APIRouter()


class QueueRequest(BaseModel):
    youtube_video_id: str
    skip_transcription: bool = False


@router.post("/queue/add")
def add_video_to_queue(request: QueueRequest):
    """Add a video to the queue."""
    try:
        video_id = extract_video_id(request.youtube_video_id)
        video_title = get_video_title(video_id)
        if not video_title:
            video_title = f"YouTube Video {video_id}"

        queue_id = add_to_queue(video_id, video_title)

        return JSONResponse({
            "status": "added",
            "queue_id": queue_id,
            "youtube_id": video_id,
            "title": video_title
        })
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
            return JSONResponse({
                "status": "queue_empty",
                "message": "No more items in queue"
            })

        # Remove the current first item
        remove_from_queue(next_item['id'])

        # Get the new first item (which was second)
        next_item = get_next_in_queue()

        if not next_item:
            return JSONResponse({
                "status": "queue_empty",
                "message": "No more items in queue"
            })

        return JSONResponse({
            "status": "next",
            "youtube_id": next_item['youtube_id'],
            "title": next_item['title'],
            "queue_id": next_item['id']
        })
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
