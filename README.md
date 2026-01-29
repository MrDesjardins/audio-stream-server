
# Install Dependencies

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

## Costs

Approximate API costs:
- Whisper transcription: $0.006 per minute of audio
- ChatGPT summarization (gpt-4o-mini): ~$0.001-0.01 per summary
- Gemini summarization (gemini-1.5-flash): Free tier available

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

# Lint

```sh
uv run ruff check --fix
uv run mypy .
uv run black .
```