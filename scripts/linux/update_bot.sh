#!/bin/bash

echo "[>>] Starting backup process..."

# Get project root directory (go up from scripts/linux)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

# Set default branch
BRANCH="main"

# If parameter provided, use it as branch
if [ ! -z "$1" ]; then
    BRANCH="$1"
fi

# Backup important files
mkdir -p backup/logs

echo "[>>] Backing up configuration and logs..."
# Copy config file
if [ -f ".env" ]; then
    cp .env backup/.env
fi

# Copy logs directory
if [ -d "logs" ]; then
    cp -r logs/* backup/logs/ 2>/dev/null || true
fi

echo "[>>] Updating code from git (branch: $BRANCH)..."
git fetch origin
if [ $? -ne 0 ]; then
    echo "❌ Failed to fetch from Git"
    read -p "Press any key to exit..."
    exit 1
fi

git pull origin "$BRANCH"
if [ $? -ne 0 ]; then
    echo "❌ Failed to pull changes"
    read -p "Press any key to exit..."
    exit 1
fi

echo "[>>] Restoring backup files..."
# Restore important files
if [ -f "backup/.env" ]; then
    cp backup/.env .env
fi

if [ -d "backup/logs" ]; then
    cp -r backup/logs/* logs/ 2>/dev/null || true
fi

echo "[>>] Updating Python dependencies..."
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    pip install -r requirements.txt --upgrade
    echo "✓ Dependencies updated"
else
    echo "⚠ Virtual environment not found"
fi

echo "[>>] Update completed successfully!"
sleep 3
