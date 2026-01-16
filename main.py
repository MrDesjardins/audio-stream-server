# file: youtube_streamer.py
import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import subprocess
import threading

# Configurable host and port
host = os.environ.get("FASTAPI_HOST", "127.0.0.1")
api_port = int(os.environ.get("FASTAPI_API_PORT", 8000))

app = FastAPI()

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Global process/thread for streaming
current_process = None
ffmpeg_thread = None
process_lock = threading.Lock()  # Ensure thread safety


class StreamRequest(BaseModel):
    youtube_video_id: str


def start_youtube_stream(youtube_video_id: str):
    """Start yt-dlp -> ffmpeg streaming to stdout"""
    global current_process
    url = f"https://www.youtube.com/watch?v={youtube_video_id}"
    yt_cmd = [
      "/usr/local/bin/yt-dlp",
      "-f",
      "bestaudio",
      "--extract-audio",
      "--audio-format", "mp3",
      "-o", "-",  # output to stdout
      url
    ]
    ffmpeg_cmd = [
        "ffmpeg",
        "-i",
        "pipe:0",
        "-f",
        "mp3",
        "pipe:1",
    ]

    yt_proc = subprocess.Popen(yt_cmd, stdout=subprocess.PIPE)
    ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=yt_proc.stdout, stdout=subprocess.PIPE)
    yt_proc.stdout.close()
    current_process = ffmpeg_proc
    ffmpeg_proc.wait()
    current_process = None


@app.post("/stream")
def stream_video(request: StreamRequest):
    global ffmpeg_thread, current_process
    with process_lock:
        # Stop existing stream if any
        if current_process:
            current_process.terminate()
            current_process = None

        # Start new stream in a thread
        def target():
            start_youtube_stream(request.youtube_video_id)

        ffmpeg_thread = threading.Thread(target=target, daemon=True)
        ffmpeg_thread.start()
        return {"status": "stream started", "youtube_video_id": request.youtube_video_id}


@app.post("/stop")
def stop_stream():
    global current_process
    with process_lock:
        if current_process:
            current_process.terminate()
            current_process = None
            return {"status": "stream stopped"}
        else:
            raise HTTPException(status_code=400, detail="No stream running")


@app.get("/status")
def get_status():
    return {"status": "streaming" if current_process else "idle"}


@app.get("/mystream")
def stream_audio():
    """Serve current ffmpeg stdout as audio"""
    if current_process is None:
        raise HTTPException(status_code=400, detail="No active stream")
    return StreamingResponse(current_process.stdout, media_type="audio/mpeg")


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "host": host,
        "api_port": api_port
    })


if __name__ == "__main__":
    import uvicorn
    print(f"Starting API on {host}:{api_port}")
    uvicorn.run("main:app", host=host, port=api_port, reload=True)
