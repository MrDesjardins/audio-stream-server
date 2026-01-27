"""
Transcription routes.
"""

import os
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from config import get_config
from services.background_tasks import get_transcription_queue, TranscriptionJob, JobStatus

logger = logging.getLogger(__name__)
router = APIRouter()
config = get_config()


@router.get("/transcription/status/{video_id}")
def get_transcription_status(video_id: str):
    """Get the transcription status for a specific video."""
    if not config.transcription_enabled:
        raise HTTPException(status_code=400, detail="Transcription not enabled")

    try:
        queue = get_transcription_queue()
        job = queue.get_job_status(video_id)

        if job is None:
            return JSONResponse(
                {
                    "video_id": video_id,
                    "status": "not_found",
                    "error": None,
                    "trilium_note_id": None,
                    "trilium_note_url": None,
                    "summary": None,
                }
            )

        return JSONResponse(
            {
                "video_id": video_id,
                "status": job.status.value,
                "error": job.error,
                "trilium_note_id": job.trilium_note_id,
                "trilium_note_url": job.trilium_note_url,
                "summary": job.summary,
            }
        )

    except Exception as e:
        logger.error(f"Error getting transcription status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/transcription/start/{video_id}")
def start_transcription(video_id: str):
    """Manually trigger transcription for a video (if audio file exists)."""
    if not config.transcription_enabled:
        raise HTTPException(status_code=400, detail="Transcription not enabled")

    audio_path = config.get_audio_path(video_id)

    if not os.path.exists(audio_path):
        raise HTTPException(
            status_code=404,
            detail=f"Audio file not found for video {video_id}. Please stream the video first.",
        )

    try:
        queue = get_transcription_queue()
        job = TranscriptionJob(video_id=video_id, audio_path=audio_path)
        queue.add_job(job)

        return JSONResponse({"status": "queued", "video_id": video_id})

    except Exception as e:
        logger.error(f"Error starting transcription: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/transcription/summary/{video_id}")
def get_summary(video_id: str):
    """Get the summary for a specific video if available."""
    if not config.transcription_enabled:
        raise HTTPException(status_code=400, detail="Transcription not enabled")

    try:
        queue = get_transcription_queue()
        job = queue.get_job_status(video_id)

        if job is None:
            raise HTTPException(
                status_code=404, detail=f"No transcription found for video {video_id}"
            )

        if job.status not in [JobStatus.COMPLETED, JobStatus.SKIPPED]:
            return JSONResponse(
                {
                    "video_id": video_id,
                    "status": job.status.value,
                    "summary": None,
                    "error": "Transcription not yet completed",
                }
            )

        return JSONResponse(
            {
                "video_id": video_id,
                "status": job.status.value,
                "summary": job.summary,
                "trilium_note_url": job.trilium_note_url,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))
