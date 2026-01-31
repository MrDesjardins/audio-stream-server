"""API routes for weekly summaries."""

import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from typing import List, Dict

from services.database import (
    get_recent_summaries,
    get_summary_by_week_year,
    add_summary_to_queue,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/weekly-summaries")
async def list_summaries(limit: int = 10) -> List[Dict]:
    """
    Get list of recent weekly summaries.

    Args:
        limit: Maximum number of summaries to return (default: 10)

    Returns:
        List of summary records with metadata
    """
    try:
        summaries = get_recent_summaries(limit=limit)
        return summaries
    except Exception as e:
        logger.error(f"Error listing summaries: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weekly-summaries/{week_year}/audio")
async def stream_summary_audio(week_year: str):
    """
    Stream audio file for a weekly summary.

    Args:
        week_year: Week identifier (e.g., "2026-W05")

    Returns:
        FileResponse with audio/mpeg content
    """
    try:
        # Get summary from database
        summary = get_summary_by_week_year(week_year)

        if not summary:
            raise HTTPException(
                status_code=404, detail=f"Summary not found: {week_year}"
            )

        audio_path = summary.get("audio_file_path")
        if not audio_path:
            raise HTTPException(
                status_code=404, detail=f"No audio file for summary: {week_year}"
            )

        # Check if file exists
        if not Path(audio_path).exists():
            logger.error(f"Audio file not found: {audio_path}")
            raise HTTPException(
                status_code=404, detail=f"Audio file not found: {audio_path}"
            )

        # Stream the file
        return FileResponse(
            audio_path,
            media_type="audio/mpeg",
            filename=f"{week_year}.mp3",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error streaming audio for {week_year}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/add-summary/{week_year}")
async def add_summary_to_playback_queue(week_year: str) -> Dict:
    """
    Add a weekly summary to the playback queue.

    Args:
        week_year: Week identifier (e.g., "2026-W05")

    Returns:
        Dict with queue item ID and status
    """
    try:
        queue_id = add_summary_to_queue(week_year)
        return {
            "status": "success",
            "queue_id": queue_id,
            "message": f"Added summary {week_year} to queue",
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding summary to queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))
