#!/bin/bash
# Local Bot API in the foreground for systemd (no -d).
# Persistent --dir so getUpdates queued while the Python bot is down are kept.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

read_env_value() {
    tr -d '\r' < .env | sed -n "s/^$1=//p" | head -n 1
}

if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found in $PROJECT_DIR" >&2
    exit 1
fi

TELEGRAM_API_ID="$(read_env_value TELEGRAM_API_ID)"
TELEGRAM_API_HASH="$(read_env_value TELEGRAM_API_HASH)"

if [ -z "$TELEGRAM_API_ID" ] || [ -z "$TELEGRAM_API_HASH" ]; then
    echo "ERROR: TELEGRAM_API_ID / TELEGRAM_API_HASH missing in .env" >&2
    exit 1
fi

API_DATA_DIR="$PROJECT_DIR/data/telegram-bot-api"
mkdir -p "$API_DATA_DIR"

docker rm -f telegram-bot-api >/dev/null 2>&1 || true

exec docker run --name telegram-bot-api --rm \
  -p 0.0.0.0:8081:8081 \
  -v "$API_DATA_DIR:/var/lib/telegram-bot-api" \
  -e TELEGRAM_API_ID="$TELEGRAM_API_ID" \
  -e TELEGRAM_API_HASH="$TELEGRAM_API_HASH" \
  aiogram/telegram-bot-api:latest --local --dir=/var/lib/telegram-bot-api
