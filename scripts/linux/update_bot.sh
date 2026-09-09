#!/bin/bash
# Pulls code from git. Local runtime files that git already ignores
# (.env, data/, logs/, cookies, downloads, venv) stay on disk.
# .env is backed up and restored (safety net if it was ever tracked).
# logs/ is copied to backup/logs as a snapshot, but not copied back —
# restoring would overwrite new lines written during the pull.

echo "[>>] Starting backup process..."

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

BRANCH="main"
if [ -n "${1:-}" ]; then
    BRANCH="$1"
fi

mkdir -p backup/logs

echo "[>>] Backing up .env (gitignored; restore is only a safety net)..."
if [ -f ".env" ]; then
    cp .env backup/.env
fi

echo "[>>] Backing up logs to backup/logs (snapshot; live logs/ stay as-is)..."
if [ -d "logs" ]; then
    cp -r logs/. backup/logs/ 2>/dev/null || true
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
    echo "    New Python code:  sudo systemctl restart tg-bot-ytdl"
    echo "    If deploy/systemd/ changed, copy units first:"
    echo "    sudo bash scripts/linux/install_systemd.sh"
    echo "    sudo systemctl restart tg-bot-ytdl"
fi

echo "[>>] Update completed successfully!"
echo "    Logs snapshot: backup/logs  |  live logs/ left in place"
echo "    Left untouched: data/, cookies, downloads, venv contents (except pip above)."
sleep 3
