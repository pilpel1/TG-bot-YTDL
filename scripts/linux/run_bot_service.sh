#!/bin/bash
# systemd ExecStart: wait for Local API, maybe pip-upgrade yt-dlp, then exec the bot.
# No interactive prompts — this is not a terminal script.

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

mkdir -p logs data
LOG_FILE="$PROJECT_DIR/logs/ytdlp_update.log"
FLAG_FILE="$PROJECT_DIR/data/pending_ytdlp_update"

log() {
    local line="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$line"
    echo "$line" >> "$LOG_FILE"
}

read_env_value() {
    if [ -f .env ]; then
        tr -d '\r' < .env | sed -n "s/^$1=//p" | head -n 1
    fi
}

BOT_TOKEN="$(read_env_value BOT_TOKEN)"

is_local_api_ready() {
    if [ -z "$BOT_TOKEN" ]; then
        return 1
    fi
    local response
    response="$(curl -fsS --max-time 5 "http://localhost:8081/bot${BOT_TOKEN}/getMe" 2>/dev/null || true)"
    [[ "$response" == *'"ok":true'* ]]
}

if [ ! -f "venv/bin/activate" ]; then
    log "ERROR: venv/bin/activate not found at $PROJECT_DIR/venv"
    exit 1
fi

if [ -z "$BOT_TOKEN" ]; then
    log "ERROR: BOT_TOKEN not found in .env"
    exit 1
fi

log "Waiting for Local Bot API Server (2GB mode)..."
LOCAL_API_READY=0
for i in $(seq 1 45); do
    if is_local_api_ready; then
        LOCAL_API_READY=1
        log "Local API is ready (attempt $i/45)"
        break
    fi
    log "Local API not ready yet ($i/45)"
    sleep 2
done

if [ "$LOCAL_API_READY" -eq 0 ]; then
    log "WARNING: Local API did not answer getMe; bot will start and may fall back to 50MB"
fi

if [ -f "$FLAG_FILE" ]; then
    REQUESTED_VERSION="$(tr -d '\r\n' < "$FLAG_FILE" || true)"
    log "Pending yt-dlp update flag found (requested=${REQUESTED_VERSION:-unknown})"
    BEFORE="$(venv/bin/yt-dlp --version 2>/dev/null || echo unknown)"
    log "yt-dlp before pip: $BEFORE"
    if venv/bin/pip install -U yt-dlp >>"$LOG_FILE" 2>&1; then
        AFTER="$(venv/bin/yt-dlp --version 2>/dev/null || echo unknown)"
        log "yt-dlp pip install succeeded: $BEFORE -> $AFTER"
    else
        log "ERROR: pip install -U yt-dlp failed; starting bot with existing version ($BEFORE)"
    fi
    rm -f "$FLAG_FILE"
    log "Removed pending update flag"
else
    log "No pending yt-dlp update flag; starting bot"
fi

# yt-dlp looks for `deno` in PATH (YouTube JS / nsig). The official installer
# puts it in ~/.deno/bin, which systemd's short PATH usually does not include.
if [ -n "${HOME:-}" ] && [ -d "$HOME/.deno/bin" ]; then
    export PATH="$HOME/.deno/bin:$PATH"
fi

# shellcheck disable=SC1091
source venv/bin/activate
exec python bot.py
