#!/bin/bash

# Audio Stream Server - Update Script
# This script updates the application and restarts the service

set -e  # Exit on error

echo "========================================="
echo "Audio Stream Server - Update"
echo "========================================="
echo ""

# Store the current directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if service is running
SERVICE_RUNNING=false
if systemctl is-active --quiet audio-stream.service 2>/dev/null; then
    SERVICE_RUNNING=true
    echo "✓ Service is currently running"
else
    echo "ℹ Service is not running"
fi

echo ""
echo "Step 1: Pulling latest changes from git..."
echo "----------------------------------------"
git fetch origin
git pull origin main

echo ""
echo "Step 2: Installing/updating dependencies..."
echo "----------------------------------------"
uv sync

echo ""
echo "Step 3: Checking for system dependencies..."
echo "----------------------------------------"
# Check if yt-dlp, ffmpeg are installed
if ! command -v yt-dlp &> /dev/null; then
    echo "⚠ yt-dlp not found. Installing..."
    sudo apt update
    sudo apt install -y yt-dlp
else
    echo "✓ yt-dlp is installed"
fi

if ! command -v ffmpeg &> /dev/null; then
    echo "⚠ ffmpeg not found. Installing..."
    sudo apt update
    sudo apt install -y ffmpeg
else
    echo "✓ ffmpeg is installed"
fi

echo ""
echo "Step 4: Generating version file..."
echo "----------------------------------------"
uv run python generate_version.py

echo ""
echo "Step 5: Migrating database schema..."
echo "----------------------------------------"
# Run migrations (handles schema changes for existing databases)
uv run python migrate_database.py
uv run python migrate_add_metadata.py
uv run python migrate_add_queue_columns.py

# Then initialize/update schema (creates tables if they don't exist)
uv run python -c "from services.database import init_database; init_database(); print('Database schema updated successfully')"

echo ""
echo "Step 6: Restarting service..."
echo "----------------------------------------"
if [ "$SERVICE_RUNNING" = true ]; then
    echo "Restarting audio-stream service..."
    sudo systemctl restart audio-stream.service
    sleep 2

    if systemctl is-active --quiet audio-stream.service; then
        echo "✓ Service restarted successfully"
    else
        echo "✗ Service failed to start. Check logs with:"
        echo "  sudo journalctl -u audio-stream -n 50"
        exit 1
    fi
else
    echo "ℹ Service was not running. To start it manually, run:"
    echo "  uv run main.py"
    echo "Or start the systemd service:"
    echo "  sudo systemctl start audio-stream"
fi

echo ""
echo "========================================="
echo "Update Complete!"
echo "========================================="
echo ""
echo "Service status:"
systemctl status audio-stream.service --no-pager || echo "Service not installed or not running"
echo ""
