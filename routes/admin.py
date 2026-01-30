"""
Admin endpoints for testing and manual operations.
"""

import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from config import get_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
config = get_config()


@router.post("/weekly-summary/trigger")
def trigger_weekly_summary():
    """
    Manually trigger the weekly summary generation.

    Useful for testing the weekly summary feature without waiting for Friday 11pm.
    """
    if not config.weekly_summary_enabled:
        raise HTTPException(status_code=400, detail="Weekly summary feature is disabled")

    try:
        from services.scheduler import trigger_weekly_summary_now

        logger.info("Manual trigger of weekly summary requested")
        trigger_weekly_summary_now()

        return JSONResponse(
            {
                "status": "triggered",
                "message": "Weekly summary generation started. Check logs for progress.",
            }
        )

    except Exception as e:
        logger.error(f"Error triggering weekly summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weekly-summary/next-run")
def get_next_run_time():
    """
    Get the next scheduled run time for the weekly summary job.
    """
    if not config.weekly_summary_enabled:
        raise HTTPException(status_code=400, detail="Weekly summary feature is disabled")

    try:
        from services.scheduler import get_next_run_time

        next_run = get_next_run_time()

        if next_run:
            return JSONResponse(
                {
                    "status": "scheduled",
                    "next_run_time": next_run,
                    "message": f"Next weekly summary will run at {next_run}",
                }
            )
        else:
            return JSONResponse(
                {"status": "not_scheduled", "message": "Weekly summary job is not scheduled"}
            )

    except Exception as e:
        logger.error(f"Error getting next run time: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
