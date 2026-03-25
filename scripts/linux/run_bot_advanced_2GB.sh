#!/bin/bash

echo "========================================"
echo "  Bot with Local Server Manager"
echo "========================================"
echo

# Get project root directory (go up from scripts/linux)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

if [ ! -f "venv/bin/activate" ]; then
    echo "ERROR: venv/bin/activate not found."
    echo "The advanced WSL flow expects a single Linux virtual environment named 'venv'."
    read -p "Press any key to exit..."
    exit 1
fi

read_env_value() {
    tr -d '\r' < .env | sed -n "s/^$1=//p" | head -n 1
}

BOT_TOKEN="$(read_env_value BOT_TOKEN)"

if [ -z "$BOT_TOKEN" ]; then
    echo "ERROR: BOT_TOKEN not found in .env file"
    read -p "Press any key to exit..."
    exit 1
fi

echo "[1/4] Starting Local Bot API Server..."
echo "Starting server..."

# Start Local Bot API Server
bash scripts/linux/start_local_api.sh no-wait || exit 1

echo
echo "[2/4] Waiting for Local API Server readiness..."
LOCAL_API_READY=0
for i in {1..45}; do
    RESPONSE="$(curl -fsS --max-time 5 "http://localhost:8081/bot${BOT_TOKEN}/getMe" 2>/dev/null || true)"
    if [[ "$RESPONSE" == *'"ok":true'* ]]; then
        LOCAL_API_READY=1
        echo "✓ Local server is ready for bot requests!"
        break
    fi

    echo "  Attempt $i/45: Local API not ready yet..."
    sleep 2
done

echo
echo "[3/4] Preparing bot runtime..."
if [ "$LOCAL_API_READY" -eq 0 ]; then
    echo "⚠ Local API Server did not answer getMe in time."
    echo "  The bot will still start and fall back to 50MB mode if needed."
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
