#!/bin/bash

# Deploy script - push to GitHub and update remote server
# Usage: ./deploy.sh [commit message]

set -e

REMOTE_HOST="10.0.0.181"
REMOTE_USER="pdesjardins"
REMOTE_DIR="/home/pdesjardins/code/audio-stream-server"

# Push to GitHub
echo "Pushing to GitHub..."
git push origin main

# SSH into remote and run update script
echo "Deploying to $REMOTE_HOST..."
ssh "$REMOTE_USER@$REMOTE_HOST" "bash -l $REMOTE_DIR/update.sh"

echo ""
echo "Deploy complete!"
