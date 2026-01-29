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
        # First try to get from transcription queue (for recent videos)
        queue = get_transcription_queue()
        job = queue.get_job_status(video_id)

        if job and job.status in [JobStatus.COMPLETED, JobStatus.SKIPPED]:
            return JSONResponse(
                {
                    "video_id": video_id,
                    "status": job.status.value,
                    "summary": job.summary,
                    "trilium_note_url": job.trilium_note_url,
                }
            )

        # If not in queue, try to fetch from Trilium
        from services.trilium import check_video_exists, get_note_content
        import re

        note_info = check_video_exists(video_id)
        if note_info:
            note_id = note_info["noteId"]
            content = get_note_content(note_id)

            if content:
                # Extract summary from HTML content
                # Remove the YouTube link section at the bottom
                content = re.sub(
                    r'<p style="margin-top.*?</p>',
                    '',
                    content,
                    flags=re.DOTALL
                )

                # Convert HTML to text with line breaks
                # Replace closing tags with newlines for better formatting
                text_summary = re.sub(r'</p>', '\n\n', content)
                text_summary = re.sub(r'</h[1-3]>', '\n\n', text_summary)
                text_summary = re.sub(r'</li>', '\n', text_summary)
                text_summary = re.sub(r'<ul>', '\n', text_summary)
                text_summary = re.sub(r'</ul>', '\n', text_summary)
                # Remove remaining HTML tags
                text_summary = re.sub(r'<[^>]+>', '', text_summary)
                # Clean up excessive whitespace
                text_summary = re.sub(r'\n\s*\n\s*\n', '\n\n', text_summary)
                text_summary = text_summary.strip()

                return JSONResponse(
                    {
                        "video_id": video_id,
                        "status": "completed",
                        "summary": text_summary,
                        "trilium_note_url": note_info["url"],
                    }
                )

        # Not found anywhere
        raise HTTPException(
            status_code=404, detail=f"No summary found for video {video_id}"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))
