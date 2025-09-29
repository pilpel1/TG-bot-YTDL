#!/bin/bash

echo "[>>] Activating virtual environment..."

# Get project root directory (go up from scripts/linux)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

# Activate virtual environment
source venv/bin/activate

echo "[>>] Starting the bot..."
python bot.py

# If bot stops, keep terminal open to see error
read -p "Press any key to continue..."
