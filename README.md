# Audio Stream Server

[![Tests](https://github.com/MrDesjardins/audio-stream-server/actions/workflows/ci.yml/badge.svg)](https://github.com/MrDesjardins/audio-stream-server/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/MrDesjardins/d9131b4d9c9e24e0530314bb5410a6f9/raw/audio-stream-server-coverage.json)](https://github.com/MrDesjardins/audio-stream-server/actions)
[![Code Quality](https://github.com/MrDesjardins/audio-stream-server/actions/workflows/ci.yml/badge.svg?event=push)](https://github.com/MrDesjardins/audio-stream-server/actions)

A powerful FastAPI application that streams audio from YouTube videos as MP3 over HTTP, with automatic transcription, AI-powered summaries, and intelligent knowledge management.

## Features

### Core Streaming
- **YouTube Audio Streaming**: Stream any YouTube video as MP3 audio in real-time
- **Multi-Client Support**: Multiple users can listen to the same stream simultaneously with individual replay buffers
- **Smart Queue System**: Build playlists with persistent queue that survives page refreshes
- **Auto-Play**: Automatically plays next track when current track completes
- **Prefetching**: Pre-downloads next queue item before current track ends for seamless transitions
- **Play History**: Track all played videos with play counts, timestamps, and rich metadata
- **Mobile-First Web UI**: Responsive interface optimized for phones, tablets, and desktops
- **MediaSession API**: Rich media controls in car entertainment systems, lock screens, and notification panels

### AI-Powered Features

#### Automatic Transcription
- **Multi-Provider Support**: Choose between OpenAI Whisper or Google Gemini for transcription
- **Audio Optimization**: Automatic compression and speed-up to reduce API costs by ~33%
- **Background Processing**: Transcription happens asynchronously without blocking playback
- **Smart Caching**: Transcripts cached locally to avoid re-processing

#### Intelligent Summarization
- **Video Summaries**: AI-generated summaries of each video's content
- **Multi-Provider**: OpenAI GPT or Google Gemini (Gemini recommended for free tier)
- **Knowledge Management**: Automatic posting to Trilium Notes with deduplication
- **Rich Metadata**: Includes video title, channel, thumbnail, and YouTube link

#### Weekly Summaries
- **Automated Scheduling**: Runs every Friday at 11 PM Pacific (configurable)
- **Comprehensive Analysis**: Synthesizes all videos watched during the week
- **Key Learnings**: Extracts 15 most important insights across all content
- **Theme Detection**: Identifies common themes and patterns in your viewing
- **Text-to-Speech**: Optional TTS generation (OpenAI or ElevenLabs) for listening to summaries

#### Smart Video Suggestions
- **AI Content Discovery**: Analyzes your viewing history to suggest similar videos
- **Theme-Based**: Identifies patterns in what you watch to find relevant content
- **YouTube Integration**: Direct search with working YouTube links
- **Configurable**: Control how many videos to analyze and suggestions to generate

### Data & Analytics
- **LLM Usage Tracking**: Detailed logging of all API calls with token counts
- **Cost Monitoring**: Track spending across providers, models, and features
- **Performance Metrics**: Audio duration, file sizes, processing times
- **Flexible Filtering**: Query by date range, provider, model, or feature

### Developer Experience
- **Modern Stack**: FastAPI, Python 3.12, SQLite with type-safe models
- **Comprehensive Testing**: 76%+ test coverage with pytest
- **CI/CD**: Automated testing and linting with GitHub Actions
- **Pre-commit Hooks**: Automatic code formatting with Ruff and type checking with mypy
- **Type Safety**: Full type annotations with mypy strict mode
- **Docker Ready**: Easy deployment with systemd service support

## Quick Start

### Prerequisites

- **Operating System**: Linux (Ubuntu/Debian recommended)
- **Python**: 3.12 or higher
- **uv**: Fast Python package manager (installed automatically by setup script)

### Step 1: Clone the Repository

```bash
git clone https://github.com/MrDesjardins/audio-stream-server.git
cd audio-stream-server
```

### Step 2: Run the Setup Script

The automated setup script installs all dependencies and initializes the database:

```bash
chmod +x setup.sh
./setup.sh
```

This script will:
1. Install system dependencies (yt-dlp, ffmpeg)
2. Install uv package manager if not present
3. Install Python dependencies
4. Initialize the SQLite database
5. Create a `.env` file from `.env.example`

### Step 3: Configure Your Environment

Edit the `.env` file to customize your settings:

```bash
nano .env
```

**Minimum configuration (no AI features):**

```bash
# Server configuration
ENV=production
FASTAPI_HOST=0.0.0.0  # Listen on all interfaces (accessible from network)
FASTAPI_API_PORT=8000

# Disable AI features for basic streaming
TRANSCRIPTION_ENABLED=false
```

**Full configuration (with AI features):**

```bash
# Server configuration
ENV=production
FASTAPI_HOST=0.0.0.0
FASTAPI_API_PORT=8000

# Enable AI features
TRANSCRIPTION_ENABLED=true

# AI API Keys
OPENAI_API_KEY=sk-...  # Get from https://platform.openai.com/api-keys
GEMINI_API_KEY=...     # Get from https://makersuite.google.com/app/apikey

# Provider selection (recommended: Whisper + Gemini for best cost/quality)
TRANSCRIPTION_PROVIDER=openai  # "openai" (Whisper) or "gemini"
SUMMARY_PROVIDER=gemini        # "gemini" (free tier) or "openai"

# Trilium Notes integration (for saving summaries)
TRILIUM_URL=http://localhost:8080
TRILIUM_ETAPI_TOKEN=...        # From Trilium: Options → ETAPI
TRILIUM_PARENT_NOTE_ID=...     # Right-click note → "Copy Note ID"

# Optional features
WEEKLY_SUMMARY_ENABLED=false
BOOK_SUGGESTIONS_ENABLED=false
TTS_ENABLED=false
```

**Important settings explained:**

- **FASTAPI_HOST**:
  - `0.0.0.0` = Accessible from all network devices (recommended)
  - `127.0.0.1` = Localhost only (not accessible from other devices)
  - Or use your specific local IP (e.g., `10.0.0.181`)

- **TRANSCRIPTION_PROVIDER**:
  - `openai` = Whisper API ($0.006/minute, very accurate, fast, 25MB limit)
  - `mistral` = Voxtral Mini ($0.003/minute, cost-effective, good quality, 15 min limit)
  - `gemini` = Gemini 1.5 Flash (free tier available, good quality, no limits)

- **SUMMARY_PROVIDER**:
  - `gemini` = Gemini 2.5 Flash (recommended, free tier, fast)
  - `openai` = GPT-4o-mini (high quality, paid)

### Step 4: Test Trilium Connection (Optional)

If you enabled transcription with Trilium integration:

```bash
uv run test_trilium.py
```

This verifies:
- Trilium is reachable at your configured URL
- ETAPI token is valid
- Parent note ID exists and is accessible

### Step 5: Configure Firewall

If running on a server, allow access to port 8000:

```bash
sudo ufw allow 8000/tcp
sudo ufw reload
sudo ufw status
```

### Step 6: Run the Application

**Development mode** (with auto-reload):

```bash
uv run main.py
```

**Production mode** (as systemd service):

See [Running as a Service](#running-as-a-service) section below.

### Step 7: Access the Web Interface

Open your browser and navigate to:

```
http://localhost:8000          # If running locally
http://YOUR_SERVER_IP:8000     # If running on a server
```

You should see the web interface with:
- Search bar to enter YouTube URLs or video IDs
- Play history
- Queue management
- Transcription status (if enabled)

## Getting API Keys

### OpenAI API Key

Required for Whisper transcription or GPT summarization.

1. Visit https://platform.openai.com/api-keys
2. Sign in or create an account
3. Click "Create new secret key"
4. Copy the key (starts with `sk-`)
5. Add to `.env` file: `OPENAI_API_KEY=sk-...`

**Cost**: Whisper is $0.006 per minute of audio. For typical use (~30 hours/month), expect ~$10-15/month.

**Limitation**: Maximum 25MB file size. Audio is automatically compressed (1.5x speed, mono, 32kbps) to save costs and meet this limit. For very long videos (>2 hours), use Gemini instead.

### Google Gemini API Key

Required for Gemini transcription or summarization. Has a generous free tier.

1. Visit https://makersuite.google.com/app/apikey
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the key
5. Add to `.env` file: `GEMINI_API_KEY=...`

**Free Tier**:
- 15 requests per minute
- 1 million tokens per day
- 1,500 requests per day

For typical use, summarization and weekly summaries are essentially free.

### Mistral AI API Key

Required for Mistral Voxtral transcription. Cost-effective option at $0.003/minute.

1. Visit https://console.mistral.ai/api-keys
2. Sign in or create an account
3. Click "Create new key"
4. Copy the key
5. Add to `.env` file: `MISTRAL_API_KEY=...`

**Cost**: Voxtral Mini is $0.003 per minute of audio. For typical use (~30 hours/month), expect ~$5-8/month (50% cheaper than Whisper).

**Limitation**: Maximum 30 minutes per audio file. For longer videos, use Gemini (no limit) or split the audio.

### Trilium ETAPI Token

Required for saving transcripts and summaries to Trilium Notes.

1. Open Trilium Notes in your browser
2. Go to **Options** → **ETAPI**
3. Click "Create new token" or copy an existing one
4. Copy the token
5. Add to `.env` file: `TRILIUM_ETAPI_TOKEN=...`

**Get Parent Note ID**:
1. In Trilium, navigate to or create a note where you want summaries stored
2. Right-click the note → "Copy Note ID"
3. Add to `.env` file: `TRILIUM_PARENT_NOTE_ID=...`

### Text-to-Speech API Keys (Optional)

Required only if you want text-to-speech for weekly summaries. Choose one provider:

#### OpenAI TTS (Recommended)
**Most affordable for long-form content**

- Pricing: $15 per 1M characters (~$0.15 for a 10K character summary)
- Quality: 6 natural voices (alloy, echo, fable, onyx, nova, shimmer)
- Models: `tts-1` (standard) or `tts-1-hd` (higher quality)
- You already have the API key from transcription setup

Set in `.env`:
```bash
TTS_PROVIDER=openai
OPENAI_TTS_VOICE=alloy
OPENAI_TTS_MODEL=tts-1
```

#### ElevenLabs (Alternative)
**Higher quality voices, more expensive**

1. Visit https://elevenlabs.io/
2. Sign up or sign in
3. Go to your profile → API Keys
4. Copy your API key
5. Add to `.env` file: `ELEVENLABS_API_KEY=...`

**Free Tier**: 10,000 characters per month (~7-10 summaries)

Set in `.env`:
```bash
TTS_PROVIDER=elevenlabs
ELEVENLABS_VOICE_ID=pNInz6obpgDQGcFmaJgB
```

## Configuration Reference

### Environment Variables

All configuration is done via the `.env` file. See `.env.example` for a complete reference with descriptions.

**Core Settings:**

| Variable | Default | Description |
|----------|---------|-------------|
| `ENV` | `production` | Environment mode (`development` or `production`) |
| `FASTAPI_HOST` | `0.0.0.0` | IP address to bind to |
| `FASTAPI_API_PORT` | `8000` | Port to listen on |
| `DATABASE_PATH` | `./audio_history.db` | SQLite database location |

**Audio Settings:**

| Variable | Default | Description |
|----------|---------|-------------|
| `AUDIO_QUALITY` | `4` | MP3 quality (0=best, 9=smallest, 4=~128kbps) |
| `AUDIO_CACHE_MAX_FILES` | `10` | Number of audio files to keep cached |
| `PREFETCH_THRESHOLD_SECONDS` | `30` | When to start downloading next track |
| `TEMP_AUDIO_DIR` | `/tmp/audio-transcriptions` | Where to store audio files |

**Transcription Settings:**

| Variable | Default | Description |
|----------|---------|-------------|
| `TRANSCRIPTION_ENABLED` | `false` | Enable AI transcription features |
| `TRANSCRIPTION_PROVIDER` | `openai` | Provider: `openai` (Whisper) or `gemini` |
| `TRANSCRIPTION_MODEL` | (auto) | Model override (optional) |
| `SUMMARY_PROVIDER` | `gemini` | Provider for video summaries |
| `SUMMARY_MODEL` | (auto) | Model override (optional) |

**Trilium Integration:**

| Variable | Required When | Description |
|----------|---------------|-------------|
| `TRILIUM_URL` | Transcription enabled | Trilium instance URL |
| `TRILIUM_ETAPI_TOKEN` | Transcription enabled | ETAPI authentication token |
| `TRILIUM_PARENT_NOTE_ID` | Transcription enabled | Note ID where summaries are stored |

**Weekly Summaries:**

| Variable | Default | Description |
|----------|---------|-------------|
| `WEEKLY_SUMMARY_ENABLED` | `false` | Enable automated weekly summaries |
| `WEEKLY_SUMMARY_PROVIDER` | `gemini` | AI provider for weekly summaries |
| `WEEKLY_SUMMARY_MODEL` | (auto) | Model override (optional) |

**Smart Suggestions:**

| Variable | Default | Description |
|----------|---------|-------------|
| `BOOK_SUGGESTIONS_ENABLED` | `false` | Enable AI video suggestions |
| `BOOKS_TO_ANALYZE` | `10` | How many recent videos to analyze |
| `SUGGESTIONS_COUNT` | `4` | Number of suggestions to generate |
| `SUGGESTIONS_AI_PROVIDER` | `gemini` | AI provider for suggestions |

**Text-to-Speech:**

| Variable | Default | Description |
|----------|---------|-------------|
| `TTS_ENABLED` | `false` | Enable TTS for summaries |
| `TTS_PROVIDER` | `openai` | Provider: `openai` or `elevenlabs` |
| `OPENAI_TTS_VOICE` | `alloy` | OpenAI voice (alloy, echo, fable, onyx, nova, shimmer) |
| `OPENAI_TTS_MODEL` | `tts-1` | OpenAI model (`tts-1` or `tts-1-hd`) |
| `ELEVENLABS_API_KEY` | - | ElevenLabs API key (if using ElevenLabs) |
| `ELEVENLABS_VOICE_ID` | `pNInz6obpgDQGcFmaJgB` | ElevenLabs voice ID (Adam by default) |
| `ELEVENLABS_MODEL_ID` | `eleven_flash_v2_5` | ElevenLabs model |
| `WEEKLY_SUMMARY_AUDIO_DIR` | `/var/audio-summaries` | Where to store TTS audio files |

## API Endpoints

### Streaming Endpoints

**Start streaming a YouTube video:**
```bash
curl -X POST http://localhost:8000/stream \
  -H "Content-Type: application/json" \
  -d '{"youtube_video_id": "dQw4w9WgXcQ"}'

# Or with a full YouTube URL:
curl -X POST http://localhost:8000/stream \
  -H "Content-Type: application/json" \
  -d '{"youtube_video_id": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'

# Skip transcription for this video:
curl -X POST http://localhost:8000/stream \
  -H "Content-Type: application/json" \
  -d '{"youtube_video_id": "dQw4w9WgXcQ", "skip_transcription": true}'
```

**Get the audio stream:**
```bash
# Open in browser or media player:
http://localhost:8000/mystream
```

**Check stream status:**
```bash
curl http://localhost:8000/status
```

**Stop current stream:**
```bash
curl -X POST http://localhost:8000/stop
```

### Queue Management

**Add video to queue:**
```bash
curl -X POST http://localhost:8000/queue/add \
  -H "Content-Type: application/json" \
  -d '{"youtube_video_id": "dQw4w9WgXcQ"}'
```

**Get current queue:**
```bash
curl http://localhost:8000/queue
```

**Skip to next track:**
```bash
curl -X POST http://localhost:8000/queue/next
```

**Remove specific item from queue:**
```bash
curl -X DELETE http://localhost:8000/queue/123
```

**Clear entire queue:**
```bash
curl -X POST http://localhost:8000/queue/clear
```

### Play History

**Get play history:**
```bash
curl http://localhost:8000/history
```

**Clear play history:**
```bash
curl -X POST http://localhost:8000/history/clear
```

### Transcription & Summaries

**Get transcription status:**
```bash
curl http://localhost:8000/transcription/status/dQw4w9WgXcQ
```

**Manually trigger transcription:**
```bash
curl -X POST http://localhost:8000/transcription/start/dQw4w9WgXcQ
```

**Get summary and Trilium link:**
```bash
curl http://localhost:8000/transcription/summary/dQw4w9WgXcQ
```

### LLM Usage Analytics

**Get detailed usage statistics:**
```bash
# Recent usage (last 100 records)
curl "http://localhost:8000/admin/llm-usage/stats?limit=100"

# Filter by provider
curl "http://localhost:8000/admin/llm-usage/stats?provider=openai"
curl "http://localhost:8000/admin/llm-usage/stats?provider=gemini"

# Filter by model
curl "http://localhost:8000/admin/llm-usage/stats?model=whisper-1"
curl "http://localhost:8000/admin/llm-usage/stats?model=gpt-4o-mini"

# Filter by feature
curl "http://localhost:8000/admin/llm-usage/stats?feature=transcription"
curl "http://localhost:8000/admin/llm-usage/stats?feature=summarization"
curl "http://localhost:8000/admin/llm-usage/stats?feature=weekly_summary"

# Date range filter (ISO 8601 format)
curl "http://localhost:8000/admin/llm-usage/stats?start_date=2026-02-01T00:00:00&end_date=2026-02-03T23:59:59"

# Combine filters
curl "http://localhost:8000/admin/llm-usage/stats?provider=openai&feature=transcription&limit=50"
```

**Get aggregated summary:**
```bash
# Overall summary (all time)
curl "http://localhost:8000/admin/llm-usage/summary"

# Summary for specific date range
curl "http://localhost:8000/admin/llm-usage/summary?start_date=2026-02-01T00:00:00&end_date=2026-02-28T23:59:59"
```

**Response format:**
```json
{
  "status": "success",
  "summary": {
    "totals": {
      "call_count": 150,
      "total_prompt_tokens": 125000,
      "total_response_tokens": 45000,
      "total_tokens": 170000
    },
    "by_provider_model_feature": [
      {
        "provider": "openai",
        "model": "whisper-1",
        "feature": "transcription",
        "call_count": 50,
        "total_tokens": 50000
      }
    ]
  }
}
```

### Weekly Summary Management

**Trigger weekly summary manually:**
```bash
curl -X POST "http://localhost:8000/admin/weekly-summary/trigger"
```

or  for a specific week:

```bash
curl -X POST "http://10.0.0.181:8000/admin/weekly-summary/trigger" \
  -H "Content-Type: application/json" \
  -d '{"date": "2026-02-06"}'
```

**Get next scheduled run time:**
```bash
curl "http://localhost:8000/admin/weekly-summary/next-run"
```

## Cost Estimates

### Current Model Pricing (Per 1M Tokens)

| Model | Input | Output | Notes |
|-------|-------|--------|-------|
| **OpenAI** ||||
| gpt-4o-mini | $0.15 | $0.60 | Reliable workhorse (recommended) |
| gpt-4o | $2.50 | $10.00 | Higher quality |
| whisper-1 | - | - | $0.006 per minute, 25MB limit |
| **Mistral AI** ||||
| voxtral-mini-latest | - | - | $0.003 per minute, 15 min limit |
| **Google Gemini** ||||
| gemini-2.5-flash | $0.15 | $0.60 | Fast, comparable to gpt-4o-mini (recommended) |
| gemini-1.5-flash | $0.10 | $0.40 | Slightly older, still excellent |
| gemini-1.5-pro | $1.25 | $5.00 | Higher quality |

### Estimated Costs Per Operation

**Using recommended configuration (Whisper + Gemini 2.5 Flash):**

- **Video transcription** (Whisper): $0.006 per minute of audio
  - 10 min video = $0.06
  - 1 hour video = $0.36

**Alternative: Cost-optimized (Voxtral + Gemini 2.5 Flash):**

- **Video transcription** (Voxtral Mini): $0.003 per minute of audio (50% cheaper)
  - 10 min video = $0.03
  - 1 hour video = $0.18

- **Video summarization** (Gemini 2.5 Flash): ~$0.0003-0.001 per summary
  - Typical: 2,000 input tokens + 500 output tokens
  - Cost: (2,000 × $0.15 + 500 × $0.60) / 1,000,000 = **$0.0006**

- **Weekly summary** (Gemini 2.5 Flash): ~$0.003-0.01 per summary
  - Typical: 10,000 input tokens + 2,000 output tokens
  - Cost: (10,000 × $0.15 + 2,000 × $0.60) / 1,000,000 = **$0.0027**

- **Book suggestions** (Gemini 2.5 Flash): ~$0.0002-0.0005 per request
  - Typical: 1,000 input tokens + 100 output tokens
  - Cost: (1,000 × $0.15 + 100 × $0.60) / 1,000,000 = **$0.0002**

### Example Monthly Costs

**Light usage** (10 hours/month, 15 videos):
- Transcription: 10 hours × 60 min × $0.006 = **$3.60**
- Summarization: 15 videos × $0.0006 = **$0.01**
- Weekly summaries: 4 weeks × $0.0027 = **$0.01**
- **Total: ~$3.62/month**

**Moderate usage** (30 hours/month, 45 videos):
- Transcription: 30 hours × 60 min × $0.006 = **$10.80**
- Summarization: 45 videos × $0.0006 = **$0.03**
- Weekly summaries: 4 weeks × $0.0027 = **$0.01**
- **Total: ~$10.84/month**

**Heavy usage** (100 hours/month, 150 videos):
- Transcription: 100 hours × 60 min × $0.006 = **$36.00**
- Summarization: 150 videos × $0.0006 = **$0.09**
- Weekly summaries: 4 weeks × $0.0027 = **$0.01**
- **Total: ~$36.10/month**

### Gemini Free Tier

Gemini has a generous free tier that covers most summarization needs:
- 15 requests per minute
- 1 million tokens per day
- 1,500 requests per day

**What's free:**
- Video summarization (essentially unlimited for personal use)
- Weekly summaries (4 per month)
- Smart suggestions (as much as you need)

**What costs money:**
- Transcription with Whisper (no free option for high quality)

### Cost Tracking

Use the admin endpoints to monitor your actual usage:

```bash
# Get total tokens used this month
curl "http://localhost:8000/admin/llm-usage/summary?start_date=2026-02-01T00:00:00"

# Check Whisper usage
curl "http://localhost:8000/admin/llm-usage/stats?model=whisper-1&limit=1000"
```

Calculate costs based on current provider pricing:
- OpenAI Whisper: audio duration minutes × $0.006
- Mistral Voxtral: audio duration minutes × $0.003
- GPT-4o-mini: (prompt_tokens × $0.15 + response_tokens × $0.60) / 1,000,000
- Gemini: Usually free up to limits

## Running as a Service

### Systemd Service Setup

The application can run as a systemd service for automatic startup and management.

**1. Edit the service file:**

```bash
nano audio-stream.service
```

Update these lines with your actual username and paths:
```ini
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/audio-stream-server
```

**2. Install the service:**

```bash
sudo cp audio-stream.service /etc/systemd/system/audio-stream.service
sudo systemctl daemon-reload
```

**3. Enable and start:**

```bash
# Enable (start on boot)
sudo systemctl enable audio-stream

# Start now
sudo systemctl start audio-stream

# Check status
sudo systemctl status audio-stream
```

**4. Manage the service:**

```bash
# Restart
sudo systemctl restart audio-stream

# Stop
sudo systemctl stop audio-stream

# View logs
journalctl -u audio-stream -n 1000 -f
```

**Note:** The service automatically loads your `.env` file from the WorkingDirectory.

### Updating the Application

Use the provided update script to safely update:

```bash
./update.sh
```

This script:
1. Checks if service is running
2. Pulls latest changes from git
3. Updates Python dependencies
4. Checks and installs missing system dependencies
5. Runs database migrations
6. Restarts the service if it was running

## Development

### Setting Up Development Environment

```bash
# Clone repository
git clone https://github.com/MrDesjardins/audio-stream-server.git
cd audio-stream-server

# Run setup
./setup.sh

# Install development dependencies
uv sync --extra dev --extra test

# Install pre-commit hooks
uv run pre-commit install
```

### Running Tests

```bash
# Run all tests with coverage
uv run pytest

# Run without coverage (faster)
uv run pytest --no-cov

# Run specific test file
uv run pytest tests/services/test_database.py

# Run specific test
uv run pytest tests/services/test_database.py::TestDatabase::test_add_history

# Use the test runner script
./run_tests.sh all        # All tests with coverage
./run_tests.sh fast       # Fast mode (no coverage)
./run_tests.sh services   # Only service tests
./run_tests.sh routes     # Only route tests
```

See [TESTING.md](./TESTING.md) for comprehensive testing documentation.

### Code Quality

**Pre-commit hooks** (automatic on commit):
```bash
# One-time setup
uv run pre-commit install

# Hooks run automatically on git commit
# They auto-fix issues and add fixes to your commit
```

**Manual linting:**
```bash
# Lint and auto-fix with Ruff
uv run ruff check --fix

# Format code
uv run ruff format .

# Type checking
uv run mypy .

# Run all pre-commit hooks manually
uv run pre-commit run --all-files
```

See [LINTING.md](./LINTING.md) for detailed linting documentation.

### Project Structure

```
audio-stream-server/
├── main.py                     # FastAPI app initialization
├── config.py                   # Configuration management
├── routes/                     # API route handlers
│   ├── stream.py               # Streaming and playback
│   ├── queue.py                # Queue management
│   ├── transcription.py        # Transcription endpoints
│   └── admin.py                # Admin endpoints
├── services/                   # Core business logic
│   ├── streaming.py            # yt-dlp and ffmpeg pipeline
│   ├── broadcast.py            # Multi-client streaming
│   ├── database.py             # SQLite operations
│   ├── youtube.py              # YouTube metadata
│   ├── transcription.py        # OpenAI/Gemini transcription
│   ├── summarization.py        # AI summarization
│   ├── trilium.py              # Trilium Notes integration
│   ├── background_tasks.py     # Async processing
│   ├── llm_clients.py          # AI client wrappers
│   └── cache.py                # Audio and transcript caching
├── templates/
│   └── index.html              # Jinja2 web interface
├── static/
│   ├── style.css               # Responsive dark theme
│   └── fonts/                  # Self-hosted fonts
└── tests/                      # Comprehensive test suite
    ├── services/
    └── routes/
```

### Database Migrations

Database schema updates are handled by migration scripts:

```bash
# Run all migrations (done automatically by update.sh)
uv run python migrate_database.py
uv run python migrate_add_metadata.py
uv run python migrate_add_queue_columns.py
```

Each migration:
- Creates a backup before making changes
- Is idempotent (safe to run multiple times)
- Preserves all existing data

### Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for development guidelines, including:
- Code style requirements
- Type annotation standards
- Path handling with `expand_path()`
- Testing requirements (76% minimum coverage)
- Pre-commit hook usage

### CI/CD

GitHub Actions automatically:
- Runs tests on every push and PR
- Generates coverage reports
- Runs code quality checks (Ruff, mypy)
- Posts coverage to PR comments

See [CI_SETUP.md](./CI_SETUP.md) for CI configuration details.

## Architecture

### Streaming Pipeline

1. **Input**: Client sends YouTube video ID via `/stream` endpoint
2. **Extract**: `yt-dlp` extracts best audio from YouTube → stdout
3. **Convert**: `ffmpeg` converts audio to MP3 → stdout
4. **Broadcast**: `StreamBroadcaster` reads from ffmpeg and broadcasts to all connected clients
5. **Multi-client**: Multiple clients can stream simultaneously via `/mystream` endpoint
6. **Playback**: HTML5 audio player consumes the stream

### Multi-Client Streaming

- **StreamBroadcaster**: Manages concurrent client connections with replay buffers
- **Replay Buffer**: Last 100 chunks (~800KB) for reconnecting clients
- **Client Queues**: Each client gets their own queue of audio chunks
- **Instant Resume**: Reconnecting clients receive buffered content immediately
- **Thread Safety**: Process lock ensures thread-safe access to global state

### Transcription Pipeline

1. **Capture**: Audio saved to file while streaming (using ffmpeg `tee` muxer)
2. **Queue**: Background worker picks up transcription job
3. **Deduplicate**: Check Trilium for existing note
4. **Transcribe**: Call OpenAI Whisper or Gemini with audio file
5. **Summarize**: Generate AI summary of transcript
6. **Post**: Create Trilium note with formatted content
7. **Cleanup**: Delete temporary audio file
8. **Cache**: Store transcript and summary for future use

### Background Processing

- Single background worker thread processes jobs sequentially
- Main thread handles HTTP requests and streaming
- Thread-safe queue for job processing
- Jobs tracked with status: PENDING → TRANSCRIBING → SUMMARIZING → POSTING → COMPLETED

## Troubleshooting

### Common Issues

**Port already in use:**
```bash
# Find process using port 8000
sudo lsof -i :8000

# Kill the process
sudo kill -9 <PID>
```

**yt-dlp not found:**
```bash
# Reinstall yt-dlp
sudo curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp
sudo chmod a+rx /usr/local/bin/yt-dlp
```

**ffmpeg not installed:**
```bash
sudo apt update
sudo apt install -y ffmpeg
```

**Database locked:**
```bash
# Stop the service
sudo systemctl stop audio-stream

# Check for locks
lsof audio_history.db

# Restart service
sudo systemctl start audio-stream
```

**Trilium connection fails:**
```bash
# Test connection
uv run test_trilium.py

# Check Trilium is running
curl http://localhost:8080

# Verify ETAPI token in Trilium settings
```

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- Audio processing with [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org/)
- AI powered by [OpenAI](https://openai.com/) and [Google Gemini](https://deepmind.google/technologies/gemini/)
- Knowledge management with [Trilium Notes](https://github.com/zadam/trilium)
