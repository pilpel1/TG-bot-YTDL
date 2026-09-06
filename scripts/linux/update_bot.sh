#!/bin/bash
# Pulls code from git. Local runtime files that git already ignores
# (.env, data/, logs/, cookies, downloads, venv) are left on disk.
# Only .env is backed up/restored as a safety net, in case it was
# ever tracked. Do not copy data/ or logs/ over themselves — that
# can wipe a pending-update flag or overwrite new log lines.

echo "[>>] Starting backup process..."

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

BRANCH="main"
if [ -n "${1:-}" ]; then
    BRANCH="$1"
fi

mkdir -p backup

echo "[>>] Backing up .env (gitignored; restore is only a safety net)..."
if [ -f ".env" ]; then
    cp .env backup/.env
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

if [ -f "backup/.env" ]; then
    cp backup/.env .env
fi

echo "[>>] Updating Python dependencies (exactly what requirements.txt asks)..."
if [ -f "venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
    pip install -r requirements.txt
    echo "✓ Dependencies updated"
else
    echo "⚠ Virtual environment not found"
fi

if systemctl list-unit-files tg-bot-ytdl.service >/dev/null 2>&1; then
    echo
    echo "[>>] systemd unit tg-bot-ytdl is installed."
    echo "    New code is on disk; restart to load it:"
    echo "    sudo systemctl restart tg-bot-ytdl"
fi

echo "[>>] Update completed successfully!"
echo "    Left untouched: data/, logs/, cookies, downloads, venv contents (except pip above)."
sleep 3
