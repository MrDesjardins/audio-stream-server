# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Audio Stream Server is a FastAPI application that streams audio from YouTube videos as MP3 over HTTP. It uses yt-dlp to extract audio and ffmpeg to convert and stream it in real-time. The application provides a simple web interface for controlling playback.

## Development Commands

### Install Dependencies
```sh
uv sync
```

### Run the Application
```sh
# Local development (localhost only)
FASTAPI_HOST=127.0.0.1 FASTAPI_API_PORT=8000 uv run main.py

# Network accessible (replace with your local IP)
FASTAPI_HOST=10.0.0.181 FASTAPI_API_PORT=8000 uv run main.py
```

### System Dependencies
Required system packages:
- `yt-dlp` - YouTube audio extraction
- `ffmpeg` - Audio conversion and streaming
- `icecast2` - Optional for streaming infrastructure

Install with:
```sh
sudo apt update
sudo apt install -y yt-dlp ffmpeg icecast2
```

Note: The application expects `yt-dlp` to be at `/usr/local/bin/yt-dlp` (see main.py:30).

## Architecture

### Project Structure

```
audio-stream-server/
├── main.py              # FastAPI server and API endpoints
├── templates/
│   └── index.html       # Jinja2 HTML template (mobile-friendly)
└── static/
    └── style.css        # Blue-violet dark theme styles
```

### Core Components

**Streaming Pipeline**:
1. Client sends YouTube video ID via `/stream` endpoint
2. `yt-dlp` extracts best audio from YouTube → stdout
3. `ffmpeg` converts audio to MP3 → stdout
4. FastAPI streams ffmpeg output to clients via `/mystream` endpoint
5. HTML5 audio player consumes the stream

**Process Management**:
- `current_process` (global): Holds the active ffmpeg process
- `ffmpeg_thread` (global): Background thread running the streaming pipeline
- `process_lock` (threading.Lock): Ensures thread-safe access to global state
- Only one stream can be active at a time (new streams terminate the current one)

### API Endpoints

- `POST /stream` - Start streaming a YouTube video (accepts JSON: `{youtube_video_id: string}`)
- `POST /stop` - Stop the current stream
- `GET /status` - Check if streaming or idle
- `GET /mystream` - The actual audio stream (audio/mpeg)
- `GET /` - Web interface (HTML)

### Features

**YouTube URL Parsing**:
- Accepts both video IDs and full YouTube URLs
- Automatically extracts video ID from URLs like:
  - `https://www.youtube.com/watch?v=VIDEO_ID`
  - `https://youtu.be/VIDEO_ID`
  - URLs with additional parameters (timestamps, playlists, etc.)

**Local History**:
- Browser localStorage tracks last 10 played videos
- Each history item shows video ID and relative timestamp
- Click any history item to replay
- Clear history button with confirmation
- Automatically deduplicates entries (moves to top when replayed)

### Frontend

**Technology Stack**:
- Jinja2 templates for server-side rendering
- Font Awesome 6.5.1 (CDN) for icons
- Vanilla JavaScript for interactivity
- Mobile-first responsive CSS with blue-violet dark theme

**Design Features**:
- Gradient backgrounds and text effects
- Animated status indicators
- Touch-friendly controls (min 44px tap targets)
- Responsive breakpoints: mobile (default), tablet (768px+), desktop

### Configuration

Environment variables:
- `FASTAPI_HOST` - Host to bind to (default: 127.0.0.1)
- `FASTAPI_API_PORT` - Port to bind to (default: 8000)

These values are injected into the HTML template via Jinja2 for dynamic audio player URLs.

## Deployment

### Systemd Service

The application can run as a systemd service using `audio-stream.service`:

```sh
# Install service
sudo cp audio-stream.service /etc/systemd/system/audio-stream.service
sudo systemctl daemon-reload
sudo systemctl enable audio-stream
sudo systemctl start audio-stream
sudo systemctl status audio-stream

# View logs
journalctl -u audio-stream -f
```

**Important**: The service file contains hardcoded user (`pdesjardins`) and paths that need to be updated for different environments.

### Firewall Configuration

If running on a network:
```sh
sudo ufw allow 8000/tcp
sudo ufw allow 8001/tcp
sudo ufw reload
```

## Known Constraints

- The yt-dlp path is hardcoded to `/usr/local/bin/yt-dlp` in main.py:30
- Only one concurrent stream is supported (by design)
- No authentication or rate limiting
- Frontend URLs are dynamically generated from environment variables
