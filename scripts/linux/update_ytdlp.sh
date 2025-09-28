#!/bin/bash

echo "========================================"
echo "  Updating yt-dlp in all environments"
echo "========================================"
echo

# Get project root directory (go up from scripts/linux)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

echo "Current directory: $PROJECT_DIR"
echo

echo "[1/2] Updating yt-dlp in virtual environment..."
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    pip install --upgrade yt-dlp
    echo "✓ Virtual environment updated"
else
    echo "⚠ Virtual environment not found at: $PROJECT_DIR/venv/"
fi

echo
echo "[2/2] Checking version..."
if [ -f "venv/bin/yt-dlp" ]; then
    echo "Current version:"
    venv/bin/yt-dlp --version
else
    echo "yt-dlp not available"
fi

echo
echo "========================================"
echo "  ✅ Update Complete!"
echo "========================================"
echo
read -p "Press any key to continue..."
