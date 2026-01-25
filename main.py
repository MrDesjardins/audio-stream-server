# file: youtube_streamer.py
import os
import sys
import logging
import threading
import signal
import atexit
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Load environment variables from .env file FIRST
load_dotenv()

# Import services
from config import get_config
from services.background_tasks import init_background_tasks
from services.broadcast import StreamBroadcaster
from services.database import init_database

# Import routers
from routes.stream import router as stream_router, init_stream_globals
from routes.queue import router as queue_router
from routes.transcription import router as transcription_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/tmp/audio-transcription.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Configurable host and port
host = os.environ.get("FASTAPI_HOST", "127.0.0.1")
api_port = int(os.environ.get("FASTAPI_API_PORT", 8000))
env = os.environ.get("ENV", "production")

# Log server configuration
logger.info("=" * 60)
logger.info("SERVER CONFIGURATION")
logger.info(f"ENV: {env}")
logger.info(f"FASTAPI_HOST: {host}")
logger.info(f"FASTAPI_API_PORT: {api_port}")
logger.info(f"Stream URL will be: http://{host}:{api_port}/mystream")
logger.info("=" * 60)

# Initialize FastAPI app
app = FastAPI()

# Load configuration
config = get_config()

# Initialize database
logger.info("Initializing database")
init_database()

# Initialize background tasks if transcription is enabled
if config.transcription_enabled:
    logger.info("Transcription enabled - initializing background tasks")
    os.makedirs(config.temp_audio_dir, exist_ok=True)
    init_background_tasks()
else:
    logger.info("Transcription disabled")

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Initialize global state for streaming
process_lock = threading.Lock()
broadcaster = StreamBroadcaster()

# Shutdown state tracking
_shutdown_called = False
_shutdown_lock = threading.Lock()


def shutdown_handler(signum=None, frame=None):
    """Gracefully shutdown streaming and background tasks."""
    global _shutdown_called

    # Prevent duplicate shutdown calls
    with _shutdown_lock:
        if _shutdown_called:
            return
        _shutdown_called = True

    logger.info("Shutdown signal received, cleaning up...")

    # Stop broadcaster
    if broadcaster:
        broadcaster.stop()

    # Terminate streaming process with timeout
    with process_lock:
        # Access the stream state from the routes module
        try:
            from routes.stream import get_stream_state
            state = get_stream_state()
            if hasattr(state, '_current_process') and state._current_process:
                proc = state._current_process
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
        except Exception as e:
            logger.warning(f"Error accessing stream state during shutdown: {e}")

    # Stop background worker if transcription enabled
    if config.transcription_enabled:
        try:
            from services.background_tasks import get_transcription_queue
            queue = get_transcription_queue()
            if hasattr(queue, 'stop'):
                queue.stop()
        except Exception as e:
            logger.warning(f"Error stopping transcription queue: {e}")

    logger.info("Shutdown complete")

    # Exit the process if called by signal handler
    if signum is not None:
        sys.exit(0)


# Register shutdown handlers
signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)
atexit.register(shutdown_handler)

# Initialize stream router with global state
init_stream_globals(process_lock, broadcaster)

# Include routers
app.include_router(stream_router)
app.include_router(queue_router)
app.include_router(transcription_router)


@app.get("/")
def index(request: Request):
    """Serve the main HTML page."""
    server_host = request.url.hostname
    logger.info(f"📄 Index page requested by {request.client.host}")
    logger.info(
        f"   Audio player URL will be: http://{server_host}:{api_port}/mystream"
    )
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "host": server_host,
            "api_port": api_port,
            "transcription_enabled": config.transcription_enabled,
        },
    )


if __name__ == "__main__":
    is_reloading_on_file_change = env == "development"
    print("=" * 70)
    print("🚀 STARTING AUDIO STREAM SERVER")
    print(f"   Environment: {env}")
    print(f"   Host: {host}")
    print(f"   Port: {api_port}")
    print(f"   Stream URL: http://{host}:{api_port}/mystream")
    print(
        f"   Transcription: {'enabled' if config.transcription_enabled else 'disabled'}"
    )
    print("=" * 70)
    uvicorn.run(
        "main:app", host=host, port=api_port, reload=is_reloading_on_file_change
    )
