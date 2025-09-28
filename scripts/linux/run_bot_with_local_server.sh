#!/bin/bash

echo "========================================"
echo "  Bot with Local Server Manager"
echo "========================================"
echo

# Get project root directory (go up from scripts/linux)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

echo "[1/4] Starting Local Bot API Server..."
echo "Starting server..."

# Start Local Bot API Server
bash scripts/linux/start_local_api.sh

echo
echo "[2/4] Waiting 10 seconds for server to initialize..."
sleep 10

echo "[3/4] Checking server status..."
if curl -s http://localhost:8081 >/dev/null 2>&1; then
    echo "✓ Local server is responding!"
else
    echo "⚠ Warning: Server might not be ready yet"
fi

echo
echo "[4/4] Starting bot..."
echo "Bot will start now..."
echo

# Activate virtual environment and start bot
source venv/bin/activate
python bot.py

echo
echo "Bot stopped. Server is still running."
echo "To stop the server, run: scripts/linux/stop_local_api.sh"
