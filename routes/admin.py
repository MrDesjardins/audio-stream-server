"""
Admin endpoints for testing and manual operations.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from config import get_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
config = get_config()
templates = Jinja2Templates(directory="templates")


class WeeklySummaryTriggerRequest(BaseModel):
    """Request body for triggering weekly summary generation."""

    date: Optional[str] = None  # Format: YYYY-MM-DD (e.g., "2026-02-04")


# Client logs storage
CLIENT_LOGS_DIR = Path("/tmp/audio-stream-client-logs")
CLIENT_LOGS_FILE = CLIENT_LOGS_DIR / "client.log"
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5MB


class ClientLogEntry(BaseModel):
    """Client-side log entry."""

    level: str  # "log", "warn", "error", "debug"
    message: str
    timestamp: str
    context: Dict[str, Any] = {}


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    """Serve the LLM usage statistics dashboard page."""
    return templates.TemplateResponse("stats.html", {"request": request})


@router.post("/weekly-summary/trigger")
def trigger_weekly_summary(
    request: WeeklySummaryTriggerRequest = WeeklySummaryTriggerRequest(),
):
    """
    Manually trigger the weekly summary generation.

    Useful for testing the weekly summary feature without waiting for Friday 11pm.

    Request body (optional):
    {
        "date": "YYYY-MM-DD"  // Generate summary for the week containing this date
    }

    If no date is provided, generates summary for the current week.
    """
    if not config.weekly_summary_enabled:
        raise HTTPException(
            status_code=400, detail="Weekly summary feature is disabled"
        )

    try:
        from services.scheduler import trigger_weekly_summary_now

        # Parse the date if provided
        target_date = None
        if request.date:
            try:
                # Parse YYYY-MM-DD format
                target_date = datetime.strptime(request.date, "%Y-%m-%d")
                logger.info(
                    f"Manual trigger of weekly summary requested for date: {request.date}"
                )
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid date format. Expected YYYY-MM-DD, got: {request.date}",
                )
        else:
            logger.info("Manual trigger of weekly summary requested for current week")

        trigger_weekly_summary_now(target_date)

        message = (
            f"Weekly summary generation started for {request.date}. Check logs for progress."
            if request.date
            else "Weekly summary generation started for current week. Check logs for progress."
        )

        return JSONResponse(
            {
                "status": "triggered",
                "message": message,
                "date": request.date if request.date else "current",
            }
        )

    except HTTPException:
        raise
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
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    feature: Optional[str] = None,
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
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
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


@router.post("/client-logs")
async def receive_client_logs(logs: List[ClientLogEntry]) -> JSONResponse:
    """
    Receive logs from the client browser.

    Stores logs in a rotating log file for debugging client-side issues,
    especially useful for car displays and mobile devices where console
    access is limited.
    """
    try:
        # Ensure log directory exists
        CLIENT_LOGS_DIR.mkdir(parents=True, exist_ok=True)

        # Rotate log file if too large
        if CLIENT_LOGS_FILE.exists() and CLIENT_LOGS_FILE.stat().st_size > MAX_LOG_SIZE:
            backup_file = (
                CLIENT_LOGS_DIR
                / f"client.log.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            CLIENT_LOGS_FILE.rename(backup_file)
            logger.info(f"Rotated client logs to {backup_file}")

        # Append logs to file
        with open(CLIENT_LOGS_FILE, "a") as f:
            for log_entry in logs:
                log_line = (
                    f"{log_entry.timestamp} [{log_entry.level.upper()}] "
                    f"{log_entry.message}"
                )
                if log_entry.context:
                    log_line += f" | Context: {log_entry.context}"
                f.write(log_line + "\n")

        logger.debug(f"Received {len(logs)} client log entries")
        return JSONResponse({"status": "ok", "received": len(logs)})

    except Exception as e:
        logger.error(f"Error storing client logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/client-logs", response_class=PlainTextResponse)
async def get_client_logs(lines: int = 100) -> str:
    """
    Get recent client-side logs.

    Query parameters:
    - lines: Number of lines to return (default: 100, max: 1000)

    Returns plain text log file content.
    """
    try:
        # Validate lines parameter
        if lines > 1000:
            lines = 1000

        if not CLIENT_LOGS_FILE.exists():
            return "No client logs available yet."

        # Read last N lines
        with open(CLIENT_LOGS_FILE, "r") as f:
            all_lines = f.readlines()
            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

        return "".join(recent_lines)

    except Exception as e:
        logger.error(f"Error reading client logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/client-logs")
async def clear_client_logs() -> JSONResponse:
    """Clear all client-side logs."""
    try:
        if CLIENT_LOGS_FILE.exists():
            CLIENT_LOGS_FILE.unlink()
            logger.info("Client logs cleared")
            return JSONResponse({"status": "cleared", "message": "Client logs deleted"})
        else:
            return JSONResponse({"status": "ok", "message": "No logs to clear"})

    except Exception as e:
        logger.error(f"Error clearing client logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
