#!/bin/bash

echo "Starting Telegram Local Bot API Server..."
echo

# Get project root directory (go up from scripts/linux)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

read_env_value() {
    tr -d '\r' < .env | sed -n "s/^$1=//p" | head -n 1
}

# Load API credentials from .env file
if [ -f ".env" ]; then
    TELEGRAM_API_ID="$(read_env_value TELEGRAM_API_ID)"
    TELEGRAM_API_HASH="$(read_env_value TELEGRAM_API_HASH)"
else
    echo "ERROR: .env file not found"
    read -p "Press any key to exit..."
    exit 1
fi

# Check if credentials were loaded
if [ -z "$TELEGRAM_API_ID" ]; then
    echo "ERROR: TELEGRAM_API_ID not found in .env file"
    read -p "Press any key to exit..."
    exit 1
fi

if [ -z "$TELEGRAM_API_HASH" ]; then
    echo "ERROR: TELEGRAM_API_HASH not found in .env file"
    read -p "Press any key to exit..."
    exit 1
fi

# Stop and remove existing container if it exists
docker rm -f telegram-bot-api 2>/dev/null

# Start new container with API credentials
docker run -d --name telegram-bot-api -p 0.0.0.0:8081:8081 \
  -e TELEGRAM_API_ID="$TELEGRAM_API_ID" \
  -e TELEGRAM_API_HASH="$TELEGRAM_API_HASH" \
  aiogram/telegram-bot-api:latest --local

if [ $? -eq 0 ]; then
    echo
    echo "Local Bot API Server started successfully!"
    echo "Server is running on http://localhost:8081"
    echo
    echo "Checking server status..."
    sleep 3
    docker ps --filter "name=telegram-bot-api"
    echo
    echo "You can now run your bot with the local API server!"

    if [ "$1" != "no-wait" ]; then
        read -p "Press any key to continue..."
    fi
else
    echo
    echo "Failed to start Local Bot API Server"
    echo "Check if Docker is running"
    if [ "$1" != "no-wait" ]; then
        read -p "Press any key to exit..."
    fi
    exit 1
fi
