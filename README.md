# Audio Stream Server

[![Tests](https://github.com/MrDesjardins/audio-stream-server/actions/workflows/ci.yml/badge.svg)](https://github.com/MrDesjardins/audio-stream-server/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/MrDesjardins/d9131b4d9c9e24e0530314bb5410a6f9/raw/audio-stream-server-coverage.json)](https://github.com/MrDesjardins/audio-stream-server/actions)
[![Code Quality](https://github.com/MrDesjardins/audio-stream-server/actions/workflows/ci.yml/badge.svg?event=push)](https://github.com/MrDesjardins/audio-stream-server/actions)

Stream audio from YouTube videos as MP3 over HTTP with automatic transcription and AI-powered summaries.

## Install Dependencies

```sh
sudo apt update
sudo apt install -y yt-dlp ffmpeg icecast2

sudo curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp
sudo chmod a+rx /usr/local/bin/yt-dlp

sudo mv /usr/local/bin/yt-dlp /usr/bin/yt-dlp
sudo chmod a+rx /usr/bin/yt-dlp
export PATH="/usr/local/bin:$PATH"

yt-dlp --version

uv sync
```

# Configure

```
sudo nano /etc/icecast2/icecast.xml
```

Change:
```
<hostname>mini-pc</hostname>
<location>Home</location>
<admin>patrick@localhost</admin>
<listen-socket>
   <port>8000</port>
   <bind-address>0.0.0.0</bind-address> <!-- listen on all IPs -->
</listen-socket>
```

# Transcription Configuration (Optional)

The application supports automatic transcription and summarization of YouTube audio using OpenAI Whisper and ChatGPT/Gemini. Transcripts and summaries are automatically posted to Trilium Notes.

## Quick Setup with .env File

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and fill in your values:
   ```bash
   nano .env
   ```

3. **Important**: Set `FASTAPI_HOST` for network access:
   ```bash
   # For network access (recommended):
   FASTAPI_HOST=0.0.0.0

   # For localhost only:
   FASTAPI_HOST=127.0.0.1
   ```

4. Required variables for transcription:
   ```bash
   TRANSCRIPTION_ENABLED=true
   OPENAI_API_KEY=sk-...
   TRILIUM_URL=http://localhost:8080
   TRILIUM_ETAPI_TOKEN=your_etapi_token_here
   TRILIUM_PARENT_NOTE_ID=root_note_id_where_summaries_are_stored
   ```

The application will automatically load settings from `.env` when it starts.

## Getting API Keys

### OpenAI API Key
1. Go to https://platform.openai.com/api-keys
2. Create a new API key
3. Copy the key (starts with `sk-`)

### Gemini API Key (Alternative to OpenAI for summarization)
1. Go to https://makersuite.google.com/app/apikey
2. Create a new API key
3. Copy the key

### Trilium ETAPI Token
1. Open Trilium Notes
2. Go to Options → ETAPI
3. Create a new token or copy existing one
4. Get the parent note ID where you want summaries stored (right-click note → "Copy Note ID")

### Test Trilium Configuration
After setting up your `.env` file, test your Trilium connection:

```bash
uv run test_trilium.py
```

This will verify:
- Trilium is reachable at the configured URL
- ETAPI token is valid
- Parent note ID exists and is accessible

## Features

When transcription is enabled:
- Audio is automatically saved while streaming
- Background worker transcribes audio using OpenAI Whisper
- Summary is generated using ChatGPT or Gemini
- Results are posted to Trilium Notes
- **Caching**: Transcripts and summaries are cached locally to avoid re-processing
- **Audio retention**: Keeps last 10 audio files for quick retry without re-downloading
- Deduplication: Videos already in Trilium are skipped
- UI shows transcription progress and allows viewing summaries
- Backup: If Trilium is unavailable, transcripts are saved to `/tmp/trilium-backup/`

## API Endpoints

### Admin Endpoints

#### LLM Usage Statistics

Track and monitor all LLM API usage including token counts, costs, and performance.

**Get detailed usage records:**
```bash
# Get recent usage (default: last 100 records)
curl "http://localhost:8000/admin/llm-usage/stats?limit=50"

# Filter by provider
curl "http://localhost:8000/admin/llm-usage/stats?provider=openai&limit=100"
curl "http://localhost:8000/admin/llm-usage/stats?provider=gemini&limit=100"

# Filter by model
curl "http://localhost:8000/admin/llm-usage/stats?model=gpt-4o&limit=50"
curl "http://localhost:8000/admin/llm-usage/stats?model=whisper-1"

# Filter by feature
curl "http://localhost:8000/admin/llm-usage/stats?feature=transcription"
curl "http://localhost:8000/admin/llm-usage/stats?feature=summarization"
curl "http://localhost:8000/admin/llm-usage/stats?feature=weekly_summary"
curl "http://localhost:8000/admin/llm-usage/stats?feature=book_suggestions"

# Date range filter (ISO 8601 format)
curl "http://localhost:8000/admin/llm-usage/stats?start_date=2026-02-01T00:00:00&end_date=2026-02-03T23:59:59"

# Combine filters
curl "http://localhost:8000/admin/llm-usage/stats?provider=openai&feature=transcription&start_date=2026-02-01T00:00:00"
```

**Response format:**
```json
{
  "status": "success",
  "count": 10,
  "limit": 50,
  "filters": {
    "start_date": "2026-02-01T00:00:00",
    "end_date": null,
    "provider": "openai",
    "model": null,
    "feature": null
  },
  "stats": [
    {
      "id": 123,
      "timestamp": "2026-02-03T03:26:28.983261+00:00",
      "provider": "openai",
      "model": "gpt-4o-mini",
      "feature": "summarization",
      "prompt_tokens": 1000,
      "response_tokens": 500,
      "reasoning_tokens": null,
      "total_tokens": 1500,
      "video_id": "dQw4w9WgXcQ",
      "metadata": {
        "transcript_length_chars": 5000,
        "summary_length_chars": 500
      },
      "created_at": "2026-02-03T03:26:28.983261+00:00"
    }
  ]
}
```

**Get aggregated summary:**
```bash
# Overall summary (all time)
curl "http://localhost:8000/admin/llm-usage/summary"

# Summary for specific date range
curl "http://localhost:8000/admin/llm-usage/summary?start_date=2026-02-01T00:00:00"
curl "http://localhost:8000/admin/llm-usage/summary?start_date=2026-02-01T00:00:00&end_date=2026-02-28T23:59:59"
```

**Response format:**
```json
{
  "status": "success",
  "filters": {
    "start_date": "2026-02-01T00:00:00",
    "end_date": null
  },
  "summary": {
    "totals": {
      "call_count": 150,
      "total_prompt_tokens": 125000,
      "total_response_tokens": 45000,
      "total_reasoning_tokens": 0,
      "total_tokens": 170000
    },
    "by_provider_model_feature": [
      {
        "provider": "openai",
        "model": "gpt-4o",
        "feature": "weekly_summary",
        "call_count": 4,
        "total_prompt_tokens": 32000,
        "total_response_tokens": 8000,
        "total_reasoning_tokens": 0,
        "total_tokens": 40000
      },
      {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "feature": "summarization",
        "call_count": 50,
        "total_prompt_tokens": 50000,
        "total_response_tokens": 20000,
        "total_reasoning_tokens": 0,
        "total_tokens": 70000
      }
    ]
  }
}
```

**Query from Python:**
```python
from services.database import get_llm_usage_stats, get_llm_usage_summary

# Get detailed stats
stats = get_llm_usage_stats(
    start_date="2026-02-01T00:00:00",
    provider="openai",
    feature="summarization",
    limit=100
)

for stat in stats:
    print(f"{stat['timestamp']}: {stat['model']} - {stat['total_tokens']} tokens")

# Get aggregated summary
summary = get_llm_usage_summary(
    start_date="2026-02-01T00:00:00",
    end_date="2026-02-28T23:59:59"
)

print(f"Total API calls: {summary['totals']['call_count']}")
print(f"Total tokens: {summary['totals']['total_tokens']:,}")
print(f"Total cost estimate: ${summary['totals']['total_tokens'] * 0.000001:.2f}")
```

**What's tracked:**
- **Transcription (Whisper)**: Audio duration, file size, transcript length
- **Transcription (Gemini)**: Prompt/response tokens, file size, transcript length
- **Summarization**: Prompt/response tokens, transcript/summary lengths
- **Weekly Summary**: Prompt/response tokens, book count, summary length
- **Book Suggestions**: Prompt/response tokens, summaries count, theme length

**Use cases:**
- Monitor API costs and usage trends
- Identify which features consume the most tokens
- Track usage per video or date range
- Optimize prompts to reduce token usage
- Budget planning and cost forecasting

#### Weekly Summary Management

**Trigger weekly summary manually:**
```bash
curl -X POST "http://localhost:8000/admin/weekly-summary/trigger"
```

**Get next scheduled run time:**
```bash
curl "http://localhost:8000/admin/weekly-summary/next-run"
```

## Costs

### Current Model Pricing (Per 1M Tokens)

| Model | Input | Output | Notes |
|-------|-------|--------|-------|
| **OpenAI** ||||
| gpt-5-nano | $0.05 | $0.40 | Ultra-lightweight for high-volume tasks |
| gpt-4o-mini | $0.15 | $0.60 | Reliable workhorse (recommended) |
| gpt-4o | $2.50 | $10.00 | Higher quality, stable pricing |
| gpt-5.2 | $1.75 | $14.00 | Extended thinking capacity |
| whisper-1 | - | - | $0.006 per minute of audio |
| **Google Gemini** ||||
| gemini-2.5-flash | $0.15 | $0.60 | Fast, comparable to gpt-4o-mini (recommended) |
| gemini-3-flash-preview | $0.50 | $3.00 | Speed-optimized preview |
| gemini-3-pro-preview | $2.00 | $12.00 | High quality (≤200k context) |

### Estimated Costs Per Operation

**Using default configuration (Whisper + Gemini 2.5 Flash):**
- **Video transcription** (Whisper): $0.006 per minute of audio
- **Video summarization** (Gemini 2.5 Flash): ~$0.0003-0.001 per summary
  - Typical: 2,000 input tokens (transcript) + 500 output tokens
  - Cost: (2,000 × $0.15 + 500 × $0.60) / 1,000,000 = **$0.0006**
- **Weekly summary** (Gemini 2.5 Flash): ~$0.003-0.01 per summary
  - Typical: 10,000 input tokens + 2,000 output tokens
  - Cost: (10,000 × $0.15 + 2,000 × $0.60) / 1,000,000 = **$0.0027**
- **Book suggestions** (Gemini 2.5 Flash): ~$0.0002-0.0005 per request
  - Typical: 1,000 input tokens + 100 output tokens
  - Cost: (1,000 × $0.15 + 100 × $0.60) / 1,000,000 = **$0.0002**

**Example monthly cost** (watching 30 hours/month):
- Transcription: 30 hours × 60 min × $0.006 = **$10.80**
- Summarization: 30 videos × $0.0006 = **$0.02**
- Weekly summaries: 4 weeks × $0.0027 = **$0.01**
- **Total: ~$10.83/month**

**Gemini Free Tier:**
- 15 requests per minute
- 1 million tokens per day
- Summarization and weekly summaries are essentially free under these limits
- Only transcription (Whisper) has costs

**Cost tracking:**
Use the `/admin/llm-usage/stats` and `/admin/llm-usage/summary` endpoints to monitor your actual usage and calculate precise costs based on current provider pricing.

# Server configuration

```sh
sudo ufw allow 8000/tcp
sudo ufw reload
sudo ufw status
```

# Run

If you're using a `.env` file (recommended):

```sh
# Simply run the application - it will read from .env automatically
uv run main.py
```

Or pass environment variables on the command line:

```sh

FASTAPI_HOST=127.0.0.1 FASTAPI_API_PORT=8000 uv run main.py

# Network accessible
FASTAPI_HOST=10.0.0.181 FASTAPI_API_PORT=8000 uv run main.py
```

**Note**: Command-line environment variables override values from `.env` file.

# Service

The application can run as a systemd service. **The `.env` file will be automatically loaded** when running as a service because it's in the WorkingDirectory.

```sh
# Make sure your .env file is configured first
nano .env

# Install and start the service
sudo cp audio-stream.service /etc/systemd/system/audio-stream.service
sudo systemctl daemon-reload
sudo systemctl enable audio-stream
sudo systemctl start audio-stream
sudo systemctl restart audio-stream
sudo systemctl stop audio-stream
sudo systemctl status audio-stream
```

**Note**: Environment variables in the `.service` file (if uncommented) will override values from `.env`.

# Debug log

```sh
journalctl -u audio-stream -n 100 -f
```

# Development

## Pre-commit Hooks (Automatic Linting)

Pre-commit hooks automatically lint and fix code before each commit:

```sh
# One-time setup: install the hooks
uv run pre-commit install

# The hooks now run automatically on `git commit`
# They will auto-fix issues and add fixes to your commit
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for detailed development guidelines.

## Manual Linting

```sh
# Lint and auto-fix with Ruff
uv run ruff check --fix

# Format code with Ruff
uv run ruff format .

# Type checking
uv run mypy .

# Run all pre-commit hooks manually
uv run pre-commit run --all-files
```
