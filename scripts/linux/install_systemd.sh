#!/bin/bash
# Writes systemd units for THIS checkout. Detects repo path and the user
# who should run the bot. Does not start the services unless --start is passed.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE_DIR="$PROJECT_DIR/deploy/systemd"
START_AFTER_INSTALL=0

if [ "${1:-}" = "--start" ]; then
    START_AFTER_INSTALL=1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run with sudo so units can be written to /etc/systemd/system/"
    echo "  sudo bash scripts/linux/install_systemd.sh"
    exit 1
fi

if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    SERVICE_USER="$SUDO_USER"
else
    SERVICE_USER="$(stat -c '%U' "$PROJECT_DIR")"
fi
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"

if [ ! -f "$TEMPLATE_DIR/tg-bot-ytdl.service" ] || [ ! -f "$TEMPLATE_DIR/telegram-bot-api.service" ]; then
    echo "ERROR: unit templates not found in $TEMPLATE_DIR"
    exit 1
fi

if [ ! -f "$PROJECT_DIR/venv/bin/activate" ]; then
    echo "ERROR: venv not found at $PROJECT_DIR/venv"
    exit 1
fi

if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "ERROR: .env not found at $PROJECT_DIR/.env"
    exit 1
fi

write_unit() {
    local template="$1"
    local dest="$2"
    sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
        -e "s|__SERVICE_USER__|$SERVICE_USER|g" \
        -e "s|__SERVICE_GROUP__|$SERVICE_GROUP|g" \
        "$template" > "$dest"
}

write_unit "$TEMPLATE_DIR/telegram-bot-api.service" /etc/systemd/system/telegram-bot-api.service
write_unit "$TEMPLATE_DIR/tg-bot-ytdl.service" /etc/systemd/system/tg-bot-ytdl.service

systemctl daemon-reload

echo "Installed systemd units:"
echo "  PROJECT_DIR=$PROJECT_DIR"
echo "  USER=$SERVICE_USER  GROUP=$SERVICE_GROUP"
echo "  /etc/systemd/system/telegram-bot-api.service"
echo "  /etc/systemd/system/tg-bot-ytdl.service"

if [ "$START_AFTER_INSTALL" -eq 1 ]; then
    systemctl enable --now telegram-bot-api.service
    systemctl enable --now tg-bot-ytdl.service
    echo "Services enabled and started."
    exit 0
fi

echo
echo "Units are installed but not started (so an already-running bot is not clobbered)."
echo "After you stop the old process:"
echo "  sudo systemctl enable --now telegram-bot-api.service"
echo "  sudo systemctl enable --now tg-bot-ytdl.service"
echo "Or rerun: sudo bash scripts/linux/install_systemd.sh --start"
