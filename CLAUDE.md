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

**Using .env file** (recommended):
```sh
# Copy example and edit with your settings
cp .env.example .env
nano .env

# Run the application
uv run main.py
```

**Using environment variables** (alternative):
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
├── main.py                     # FastAPI server and API endpoints
├── config.py                   # Configuration management
├── background_tasks.py         # Background worker for transcription
├── transcription_service.py    # OpenAI Whisper integration
├── summarization_service.py    # ChatGPT/Gemini integration
├── trilium_service.py          # Trilium Notes ETAPI integration
├── templates/
│   └── index.html              # Jinja2 HTML template (mobile-friendly)
└── static/
    └── style.css               # Blue-violet dark theme styles
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

**Streaming Endpoints**:
- `POST /stream` - Start streaming a YouTube video (accepts JSON: `{youtube_video_id: string}`)
- `POST /stop` - Stop the current stream
- `GET /status` - Check if streaming or idle
- `GET /mystream` - The actual audio stream (audio/mpeg)
- `GET /` - Web interface (HTML)

**Transcription Endpoints** (when `TRANSCRIPTION_ENABLED=true`):
- `GET /transcription/status/{video_id}` - Get transcription status, note URL, and summary
- `POST /transcription/start/{video_id}` - Manually trigger transcription for saved audio
- `GET /transcription/summary/{video_id}` - Get summary and Trilium link

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

## Transcription Feature

**Status**: Implemented (optional feature, disabled by default)

### Overview

The application supports automatic transcription and summarization of YouTube audio streams. When enabled, audio is transcribed using OpenAI Whisper, summarized using ChatGPT or Gemini, and posted to Trilium Notes for knowledge management.

### Architecture Components

#### New Files

**Service Layer**:
- `config.py` - Configuration management with environment variable loading and validation
- `transcription_service.py` - OpenAI Whisper API integration for audio transcription
- `summarization_service.py` - ChatGPT and Gemini API integration for summary generation
- `trilium_service.py` - Trilium Notes ETAPI integration with deduplication

**Background Processing**:
- `background_tasks.py` - Thread-safe queue and worker thread for asynchronous transcription processing

#### Modified Files

- `main.py` - Enhanced streaming to save audio files, background worker initialization, new transcription endpoints
- `templates/index.html` - Transcription status UI, summary modal, status polling JavaScript
- `static/style.css` - Transcription section styles, modal styles, spinner animations
- `pyproject.toml` - Added dependencies: `openai`, `google-generativeai`, `httpx`

### Data Flow

**Streaming with Audio Capture**:
1. Client requests stream via `/stream` endpoint
2. `yt-dlp` extracts audio from YouTube
3. `ffmpeg` uses "tee" muxer to write to both stdout (for streaming) and file (for transcription)
4. Audio file saved to `{TEMP_AUDIO_DIR}/{video_id}.mp3`
5. Stream continues to client as before

**Background Transcription Pipeline**:
1. After streaming starts, `TranscriptionJob` added to queue
2. Background worker picks up job from queue
3. **Deduplication Check**: Query Trilium for existing note with title "YouTube: {video_id}"
4. If exists, mark job as "skipped" and return note info
5. If not exists, continue with transcription
6. **Transcription**: Call OpenAI Whisper API with audio file (3 retries with exponential backoff)
7. **Summarization**: Call ChatGPT or Gemini API with transcript
8. **Posting**: Create Trilium note via ETAPI with HTML-formatted content
9. **Cleanup**: Delete temporary audio file
10. Job status updated throughout process

### Job Status Flow

```
PENDING → CHECKING_DEDUP → [SKIPPED if exists]
                          ↓ [if not exists]
                     TRANSCRIBING → SUMMARIZING → POSTING → COMPLETED
                          ↓ [on error]
                        FAILED
```

### API Endpoints

**New Transcription Endpoints**:
- `GET /transcription/status/{video_id}` - Get current status, note URL, and summary
- `POST /transcription/start/{video_id}` - Manually trigger transcription for saved audio
- `GET /transcription/summary/{video_id}` - Get summary and Trilium link

**Enhanced Endpoints**:
- `GET /` - Now includes `transcription_enabled` flag for conditional UI rendering

### UI Components

**Transcription Status Section** (shown only if `TRANSCRIPTION_ENABLED=true`):
- Real-time status display with icons
- Progress spinner during processing
- Action buttons: "View Summary", "Open in Trilium"
- Error display with details

**Summary Modal**:
- Animated overlay modal
- Formatted summary text
- Link to full note in Trilium
- Click-outside-to-close behavior

**Status Polling**:
- Frontend polls `/transcription/status/{video_id}` every 5 seconds
- Updates UI dynamically as job progresses
- Tracks `currentVideoId` to poll correct video

### Configuration

**Required Environment Variables** (when `TRANSCRIPTION_ENABLED=true`):
```bash
TRANSCRIPTION_ENABLED=true
OPENAI_API_KEY=sk-...
SUMMARY_PROVIDER=openai  # or "gemini"
TRILIUM_URL=http://localhost:8080
TRILIUM_ETAPI_TOKEN=...
TRILIUM_PARENT_NOTE_ID=...
```

**Optional Variables**:
```bash
TEMP_AUDIO_DIR=/tmp/audio-transcriptions  # default
MAX_AUDIO_LENGTH_MINUTES=60               # not yet implemented
GEMINI_API_KEY=...                         # if SUMMARY_PROVIDER=gemini
```

### Thread Safety

**Locks and Queues**:
- `process_lock` (from original code) - Protects `current_process` and `ffmpeg_thread`
- `TranscriptionQueue.lock` - Protects job dictionary and queue operations
- `queue.Queue` - Thread-safe queue for job processing

**Concurrency Model**:
- Single background worker thread processes transcription jobs sequentially
- Main thread handles HTTP requests and streaming
- No race conditions between streaming and transcription

### Error Handling

**Transcription Failures**:
- Retry up to 3 times with exponential backoff (2^attempt seconds)
- If all retries fail, mark job as FAILED with error message

**Trilium Failures**:
- If ETAPI call fails, save transcript/summary to `/tmp/trilium-backup/{video_id}.json`
- Continue operation, don't block future transcriptions

**Audio File Cleanup**:
- Always attempt to delete temp audio file after processing
- Log error if cleanup fails, don't propagate exception

### Logging

**Log File**: `/tmp/audio-transcription.log`

**Log Levels**:
- INFO: Job lifecycle events, API calls, status changes
- WARNING: Retry attempts, deduplication results
- ERROR: API failures, file system errors
- EXCEPTION: Unexpected errors with full stack trace

### Performance Considerations

**Audio File Size**: ~1-5 MB per minute of audio

**Processing Time**:
- Transcription: 10-30 seconds for typical video
- Summarization: 2-5 seconds
- Total: ~15-40 seconds per video

**API Costs**:
- Whisper: $0.006/minute of audio
- GPT-4o-mini: ~$0.001-0.01 per summary
- Gemini Flash: Free tier available

**Disk Usage**:
- Audio files: Kept (last 10 files) for quick retry
- Transcripts/summaries: Cached in `/tmp/transcription-cache/`
- Backup files in `/tmp/trilium-backup/` persist (manual cleanup needed)

### Trilium Note Structure

**Note Format**:
- Title: `YouTube: {video_id}`
- Type: text/html
- Contains: Summary only (not full transcript)
- Attribute: `youtube_id = {video_id}` (for deduplication)

**Content Layout**:
- Markdown-formatted summary converted to HTML
- Headers (###) rendered as `<h3>` tags
- Bullet points rendered as `<ul>/<li>` tags
- Link to YouTube video at bottom

**Why summary-only?**:
- Full transcripts are very long and clutter Trilium
- Transcripts are cached locally for reference
- Summary provides the key information
- Can always re-process if full transcript is needed

### Note Creation Process

**Two-Step Approach**: Trilium's ETAPI requires separate calls to create notes and add attributes

**Implementation**:
1. **Create Note**: `POST /etapi/create-note` with parentNoteId, title, type, mime, and content
2. **Add Attribute**: `POST /etapi/attributes` with noteId, type=label, name=youtube_id, value=video_id

**Why Two Steps**: The `/etapi/create-note` endpoint does not accept an `attributes` field in the request body. Attributes must be added separately after note creation.

**Error Handling**: If attribute creation fails, the note still exists but won't be deduplicated. The backup file is saved with full data.

### Deduplication Strategy

**Rationale**: Avoid re-transcribing videos already processed

**Implementation** (using Trilium attributes):
1. Each note created has a `youtube_id` attribute with the video ID (added in step 2 of note creation)
2. Before transcribing, search Trilium: `GET /etapi/notes?search=#youtube_id="{video_id}"`
3. If found, return existing note ID and URL
4. If not found, proceed with transcription

**Benefits of attribute-based approach**:
- Works regardless of parent note structure
- More reliable than title matching
- Survives note moves/renames
- Faster than listing all children

**Edge Cases**:
- If Trilium search fails, log warning and continue (skip deduplication)
- If note exists but attribute was removed, will create duplicate

### Known Limitations

- Only one background worker (sequential processing)
- No progress indication for long transcriptions
- No retry mechanism for Trilium posting failures
- No automatic cleanup of old backup files
- `MAX_AUDIO_LENGTH_MINUTES` not yet enforced
- No speaker diarization or timestamped transcripts

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
