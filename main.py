# file: youtube_streamer.py
import os
import logging
import threading
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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/audio-transcription.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configurable host and port
host = os.environ.get("FASTAPI_HOST", "127.0.0.1")
api_port = int(os.environ.get("FASTAPI_API_PORT", 8000))

# Log server configuration
logger.info("=" * 60)
logger.info("SERVER CONFIGURATION")
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
    logger.info(f"   Audio player URL will be: http://{server_host}:{api_port}/mystream")
    return templates.TemplateResponse("index.html", {
        "request": request,
        "host": server_host,
        "api_port": api_port,
        "transcription_enabled": config.transcription_enabled
    })


if __name__ == "__main__":
    import uvicorn
    print("=" * 70)
    print("🚀 STARTING AUDIO STREAM SERVER")
    print(f"   Host: {host}")
    print(f"   Port: {api_port}")
    print(f"   Stream URL: http://{host}:{api_port}/mystream")
    print(f"   Transcription: {'enabled' if config.transcription_enabled else 'disabled'}")
    print("=" * 70)
    uvicorn.run("main:app", host=host, port=api_port, reload=True)
