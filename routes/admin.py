"""
Admin endpoints for testing and manual operations.
"""

import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from config import get_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
config = get_config()
templates = Jinja2Templates(directory="templates")


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    """Serve the LLM usage statistics dashboard page."""
    return templates.TemplateResponse("stats.html", {"request": request})


@router.post("/weekly-summary/trigger")
def trigger_weekly_summary():
    """
    Manually trigger the weekly summary generation.

    Useful for testing the weekly summary feature without waiting for Friday 11pm.
    """
    if not config.weekly_summary_enabled:
        raise HTTPException(
            status_code=400, detail="Weekly summary feature is disabled"
        )

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
        raise HTTPException(
            status_code=400, detail="Weekly summary feature is disabled"
        )

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
                {
                    "status": "not_scheduled",
                    "message": "Weekly summary job is not scheduled",
                }
            )

    except Exception as e:
        logger.error(f"Error getting next run time: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm-usage/stats")
def get_llm_usage_statistics(
    start_date: str = None,
    end_date: str = None,
    provider: str = None,
    model: str = None,
    feature: str = None,
    limit: int = 100,
):
    """
    Get LLM usage statistics with optional filters.

    Query parameters:
    - start_date: Start date in ISO format (e.g., "2024-01-01T00:00:00")
    - end_date: End date in ISO format
    - provider: Filter by provider (e.g., "openai", "gemini")
    - model: Filter by model name
    - feature: Filter by feature (e.g., "transcription", "summarization")
    - limit: Maximum number of records (default: 100, max: 1000)

    Returns detailed usage records including token counts and metadata.
    """
    try:
        from services.database import get_llm_usage_stats

        # Limit validation
        if limit > 1000:
            limit = 1000

        stats = get_llm_usage_stats(
            start_date=start_date,
            end_date=end_date,
            provider=provider,
            model=model,
            feature=feature,
            limit=limit,
        )

        return JSONResponse(
            {
                "status": "success",
                "count": len(stats),
                "limit": limit,
                "filters": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "provider": provider,
                    "model": model,
                    "feature": feature,
                },
                "stats": stats,
            }
        )

    except Exception as e:
        logger.error(f"Error getting LLM usage stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm-usage/summary")
def get_llm_usage_summary_endpoint(
    start_date: str = None,
    end_date: str = None,
):
    """
    Get aggregated LLM usage summary.

    Query parameters:
    - start_date: Start date in ISO format (optional)
    - end_date: End date in ISO format (optional)

    Returns aggregated statistics grouped by provider, model, and feature
    including total token counts and call counts.
    """
    try:
        from services.database import get_llm_usage_summary

        summary = get_llm_usage_summary(
            start_date=start_date,
            end_date=end_date,
        )

        return JSONResponse(
            {
                "status": "success",
                "filters": {
                    "start_date": start_date,
                    "end_date": end_date,
                },
                "summary": summary,
            }
        )

    except Exception as e:
        logger.error(f"Error getting LLM usage summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
