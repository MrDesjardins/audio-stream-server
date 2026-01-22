#!/bin/bash

# Audio Stream Server - Setup Script
# This script sets up the application for first-time use

set -e  # Exit on error

echo "========================================="
echo "Audio Stream Server - Setup"
echo "========================================="
echo ""

# Check if running as root for system dependencies
if [[ $EUID -ne 0 ]]; then
   echo "Note: Some operations may require sudo privileges."
   echo "You may be prompted for your password."
   echo ""
fi

# Install system dependencies
echo "Step 1: Installing system dependencies..."
echo "----------------------------------------"
sudo apt update
sudo apt install -y yt-dlp ffmpeg icecast2 python3-pip

echo ""
echo "Step 2: Installing Python package manager (uv)..."
echo "----------------------------------------"
if ! command -v uv &> /dev/null; then
    echo "uv not found, installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Source the cargo env to make uv available in current shell
    source "$HOME/.cargo/env" || true
else
    echo "uv is already installed"
fi

echo ""
echo "Step 3: Installing Python dependencies..."
echo "----------------------------------------"
uv sync

echo ""
echo "Step 4: Initializing database..."
echo "----------------------------------------"
# Run Python script to initialize database
uv run python -c "from database_service import init_database; init_database(); print('Database initialized successfully')"

echo ""
echo "Step 5: Environment configuration..."
echo "----------------------------------------"
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo "Creating .env file from .env.example..."
        cp .env.example .env
        echo "✓ .env file created. Please edit it with your settings:"
        echo "  - FASTAPI_HOST (default: 127.0.0.1)"
        echo "  - FASTAPI_API_PORT (default: 8000)"
        echo "  - TRANSCRIPTION_ENABLED (default: false)"
        echo "  - And other settings as needed"
    else
        echo "Warning: .env.example not found. You'll need to create .env manually."
    fi
else
    echo "✓ .env file already exists"
fi

echo ""
echo "========================================="
echo "Setup Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Edit .env file with your configuration"
echo "2. Run the application:"
echo "   uv run main.py"
echo ""
echo "Optional: Set up systemd service"
echo "1. Edit audio-stream.service with your paths and user"
echo "2. Install the service:"
echo "   sudo cp audio-stream.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable audio-stream"
echo "   sudo systemctl start audio-stream"
echo ""
