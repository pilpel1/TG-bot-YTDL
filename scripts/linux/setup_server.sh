#!/bin/bash
# Fresh Debian/Ubuntu server setup for this repo.
# Asks for the bot token, whether to enable 2GB mode, and whether to
# start systemd. Stops if RAM or free disk cannot fit the install.
# Warns (and asks) if they are below the recommended working minimum,
# then installs FFmpeg, a venv, Deno, and (for 2GB) Docker.
# --yes does not override the install minimum.
#
# Run as the user that should own the bot, not as root:
#   bash scripts/linux/setup_server.sh
#   bash scripts/linux/setup_server.sh --yes
#
# --yes answers Y to the yes/no questions. A token is still required:
# existing .env, or SETUP_BOT_TOKEN (and for 2GB also
# SETUP_TELEGRAM_API_ID + SETUP_TELEGRAM_API_HASH).

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help)
            sed -n '2,15p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            echo "Usage: bash scripts/linux/setup_server.sh [--yes]" >&2
            exit 1
            ;;
    esac
done

KEEP_ENV=0
WRITE_ENV=0
ENABLE_2GB=0
START_SERVICES=0
BOT_TOKEN="${SETUP_BOT_TOKEN:-}"
API_ID="${SETUP_TELEGRAM_API_ID:-}"
API_HASH="${SETUP_TELEGRAM_API_HASH:-}"

die() {
    echo "ERROR: $*" >&2
    exit 1
}

have_systemd() {
    command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]
}

is_placeholder() {
    case "$1" in
        ""|your_bot_token_here|your_api_id_here|your_api_hash_here) return 0 ;;
        *) return 1 ;;
    esac
}

read_env_value() {
    local key="$1" line
    [ -f .env ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        case "$line" in
            "${key}="*)
                printf '%s' "${line#"${key}"=}"
                return 0
                ;;
        esac
    done < .env
}

ask_yes() {
    local prompt="$1" default="${2:-y}" reply
    if [ "$ASSUME_YES" -eq 1 ] || [ ! -t 0 ]; then
        if [ "$default" = "y" ]; then
            return 0
        fi
        return 1
    fi
    read -r -p "$prompt " reply || true
    reply="${reply:-$default}"
    case "$reply" in
        y|Y|yes|YES) return 0 ;;
        *) return 1 ;;
    esac
}

ask_value() {
    local prompt="$1" current="$2"
    if [ -n "$current" ]; then
        printf '%s' "$current"
        return 0
    fi
    if [ ! -t 0 ]; then
        die "Missing value ($prompt). Run in a terminal, or set SETUP_BOT_TOKEN / SETUP_TELEGRAM_API_ID / SETUP_TELEGRAM_API_HASH"
    fi
    local value=""
    while [ -z "$value" ]; do
        read -r -p "$prompt " value || true
        if [ -z "$value" ]; then
            echo "Empty, try again."
        fi
    done
    printf '%s' "$value"
}

upsert_env_key() {
    local key="$1" value="$2" tmp
    tmp="$(mktemp)"
    if [ -f .env ] && grep -q "^${key}=" .env; then
        awk -v k="$key" -v v="$value" '
            BEGIN { found = 0 }
            $0 ~ ("^" k "=") { print k "=" v; found = 1; next }
            { print }
        ' .env > "$tmp"
    else
        if [ -f .env ]; then
            cat .env > "$tmp"
            printf '\n' >> "$tmp"
        fi
        printf '%s=%s\n' "$key" "$value" >> "$tmp"
    fi
    chmod 600 "$tmp"
    mv "$tmp" .env
}

# Install floor: venv + Deno, plus apt scratch. 2GB mode also pulls
# docker.io and the Local API image. Below this, the install itself fails.
# Recommended is higher and not required: one download keeps the source
# and the output on disk together (about 2x the file that gets sent).
INSTALL_RAM_MIB_50MB=256
INSTALL_DISK_MIB_50MB=1024
INSTALL_RAM_MIB_2GB=512
INSTALL_DISK_MIB_2GB=2048
RECOMMENDED_RAM_MIB_50MB=1024
RECOMMENDED_DISK_MIB_50MB=2048
RECOMMENDED_RAM_MIB_2GB=2048
RECOMMENDED_DISK_MIB_2GB=6144
RESOURCE_WARNINGS=0
RESOURCE_BLOCKS=0

read_mem_total_mib() {
    awk '/^MemTotal:/ { printf "%d", $2 / 1024 }' /proc/meminfo 2>/dev/null || true
}

read_disk_free_mib() {
    { df -Pk "$1" | awk 'NR==2 { printf "%d", $4 / 1024 }'; } 2>/dev/null || true
}

check_resources() {
    local install_ram install_disk rec_ram rec_disk ram_mib disk_mib
    RESOURCE_WARNINGS=0
    RESOURCE_BLOCKS=0
    if [ "$ENABLE_2GB" -eq 1 ]; then
        install_ram=$INSTALL_RAM_MIB_2GB
        install_disk=$INSTALL_DISK_MIB_2GB
        rec_ram=$RECOMMENDED_RAM_MIB_2GB
        rec_disk=$RECOMMENDED_DISK_MIB_2GB
    else
        install_ram=$INSTALL_RAM_MIB_50MB
        install_disk=$INSTALL_DISK_MIB_50MB
        rec_ram=$RECOMMENDED_RAM_MIB_50MB
        rec_disk=$RECOMMENDED_DISK_MIB_50MB
    fi

    ram_mib="$(read_mem_total_mib)"
    disk_mib="$(read_disk_free_mib "$PROJECT_DIR")"

    echo "Resource check (recommended is not required):"
    if [ -z "$ram_mib" ]; then
        echo "  RAM: could not read /proc/meminfo"
        RESOURCE_WARNINGS=$((RESOURCE_WARNINGS + 1))
    elif [ "$ram_mib" -lt "$install_ram" ]; then
        echo "  RAM: ${ram_mib} MiB (install ${install_ram}, recommended ${rec_ram}) TOO LOW"
        RESOURCE_BLOCKS=$((RESOURCE_BLOCKS + 1))
    elif [ "$ram_mib" -lt "$rec_ram" ]; then
        echo "  RAM: ${ram_mib} MiB (install ${install_ram}, recommended ${rec_ram}) below recommended"
        RESOURCE_WARNINGS=$((RESOURCE_WARNINGS + 1))
    else
        echo "  RAM: ${ram_mib} MiB (install ${install_ram}, recommended ${rec_ram}) ok"
    fi

    if [ -z "$disk_mib" ]; then
        echo "  Disk: could not read free space on $PROJECT_DIR"
        RESOURCE_WARNINGS=$((RESOURCE_WARNINGS + 1))
    elif [ "$disk_mib" -lt "$install_disk" ]; then
        echo "  Disk: ${disk_mib} MiB free on $PROJECT_DIR (install ${install_disk}, recommended ${rec_disk}) TOO LOW"
        RESOURCE_BLOCKS=$((RESOURCE_BLOCKS + 1))
    elif [ "$disk_mib" -lt "$rec_disk" ]; then
        echo "  Disk: ${disk_mib} MiB free on $PROJECT_DIR (install ${install_disk}, recommended ${rec_disk}) below recommended"
        RESOURCE_WARNINGS=$((RESOURCE_WARNINGS + 1))
    else
        echo "  Disk: ${disk_mib} MiB free on $PROJECT_DIR (install ${install_disk}, recommended ${rec_disk}) ok"
    fi

    if [ "$RESOURCE_BLOCKS" -gt 0 ]; then
        echo "ERROR: below the install minimum. apt, the venv, Deno, or Docker will fail."
        return
    fi

    if [ "$RESOURCE_WARNINGS" -gt 0 ]; then
        echo "WARNING: below the recommended minimum. Install can finish, and the bot can run."
        if [ "$ENABLE_2GB" -eq 1 ]; then
            echo "One download keeps the source and the output on disk at once (about 2x the file you send)."
            echo "A 1.5 GiB audio needs about 3 GiB free during that download, even though Telegram can send 1.5 GiB."
            if [ -z "$disk_mib" ] || [ "$disk_mib" -lt "$rec_disk" ]; then
                echo "Edge case, does not block install: if no direct audio stream exists, a fallback can download the full video and extract audio from it. That needs room for the video, not just the m4a."
            fi
        else
            echo "Files are capped at 50MB. This warning is headroom for apt, ffmpeg, and the venv, not for a large file."
        fi
    fi
}

if [ "$(id -u)" -eq 0 ]; then
    die "Do not run as root. Deno and the bot must belong to the normal user:
  bash scripts/linux/setup_server.sh"
fi

if ! command -v sudo >/dev/null 2>&1; then
    die "sudo is required for apt and systemd"
fi

if ! command -v apt-get >/dev/null 2>&1; then
    die "This script is for Debian/Ubuntu (apt). On Windows, install manually. See the README"
fi

if [ ! -f "$PROJECT_DIR/requirements.txt" ] || [ ! -f "$PROJECT_DIR/bot.py" ]; then
    die "Repo not found at $PROJECT_DIR"
fi

echo "Setting up TG-bot-YTDL on this server."
echo "User: $(id -un)    Directory: $PROJECT_DIR"
echo

existing_token="$(read_env_value BOT_TOKEN)"
if ! is_placeholder "$existing_token"; then
    if ask_yes "Found .env. Keep it as-is? [Y/n]" y; then
        KEEP_ENV=1
        BOT_TOKEN="$existing_token"
        file_id="$(read_env_value TELEGRAM_API_ID)"
        file_hash="$(read_env_value TELEGRAM_API_HASH)"
        if ! is_placeholder "$file_id"; then
            API_ID="$file_id"
        fi
        if ! is_placeholder "$file_hash"; then
            API_HASH="$file_hash"
        fi
    fi
fi

if [ "$KEEP_ENV" -eq 0 ]; then
    if [ -z "$BOT_TOKEN" ]; then
        echo "Bot token: https://t.me/BotFather  (/newbot, then copy the token)"
    fi
    BOT_TOKEN="$(ask_value "Bot token from BotFather:" "$BOT_TOKEN")"
    case "$BOT_TOKEN" in
        *:*) ;;
        *) echo "Warning: token does not look like a BotFather token (no colon). Continuing." ;;
    esac
    WRITE_ENV=1
    if [ "${SETUP_ENABLE_2GB:-}" = "0" ]; then
        ENABLE_2GB=0
    elif [ "${SETUP_ENABLE_2GB:-}" = "1" ] || ask_yes "Enable 2GB mode (Docker + Local API)? [Y/n]" y; then
        ENABLE_2GB=1
    fi
else
    if ! is_placeholder "$API_ID" && ! is_placeholder "$API_HASH"; then
        ENABLE_2GB=1
        echo "2GB mode: api_id and api_hash found in .env"
    elif [ "${SETUP_ENABLE_2GB:-}" = "0" ]; then
        ENABLE_2GB=0
    elif [ "${SETUP_ENABLE_2GB:-}" = "1" ] || ask_yes "No api_id/api_hash in .env. Install 2GB mode too? [Y/n]" y; then
        ENABLE_2GB=1
        WRITE_ENV=1
    fi
fi

if is_placeholder "$API_ID"; then
    API_ID=""
fi
if is_placeholder "$API_HASH"; then
    API_HASH=""
fi

if [ "$ENABLE_2GB" -eq 1 ]; then
    if [ -z "$API_ID" ] || [ -z "$API_HASH" ]; then
        echo "api_id and api_hash: https://my.telegram.org  (API development tools)"
    fi
    API_ID="$(ask_value "TELEGRAM_API_ID:" "$API_ID")"
    case "$API_ID" in
        ''|*[!0-9]*) die "TELEGRAM_API_ID must be a number" ;;
    esac
    API_HASH="$(ask_value "TELEGRAM_API_HASH:" "$API_HASH")"
    if is_placeholder "$API_HASH"; then
        die "TELEGRAM_API_HASH is empty"
    fi
    if have_systemd; then
        if [ "${SETUP_START:-}" = "0" ]; then
            START_SERVICES=0
        elif [ "${SETUP_START:-}" = "1" ] || ask_yes "Start the services now? [Y/n] (N = only write the systemd units)" y; then
            START_SERVICES=1
        fi
    else
        echo "systemd is not running. Skipping service units."
    fi
fi

echo
check_resources
echo
echo "Summary before changes:"
echo "  Mode: $([ "$ENABLE_2GB" -eq 1 ] && echo '2GB' || echo '50MB')"
echo "  .env: $([ "$WRITE_ENV" -eq 1 ] && echo 'will be written' || echo 'left as-is')"
if [ "$ENABLE_2GB" -eq 1 ] && have_systemd; then
    echo "  systemd: $([ "$START_SERVICES" -eq 1 ] && echo 'install and start' || echo 'install only, do not start')"
fi
if [ "$RESOURCE_BLOCKS" -gt 0 ]; then
    echo "  Resources: too low to install"
elif [ "$RESOURCE_WARNINGS" -gt 0 ]; then
    echo "  Resources: below recommended"
else
    echo "  Resources: ok"
fi
echo

if [ "$RESOURCE_BLOCKS" -gt 0 ]; then
    echo "Stopped. Nothing was installed."
    exit 1
fi

if [ "$RESOURCE_WARNINGS" -gt 0 ]; then
    if [ "$ASSUME_YES" -eq 1 ] || [ ! -t 0 ]; then
        echo "Continuing below the recommended minimum."
        echo
    elif ! ask_yes "Continue anyway? [y/N]" n; then
        echo "Stopped. Nothing was installed."
        exit 1
    fi
fi

sudo -v

echo "[1] apt: python3, ffmpeg, unzip, curl..."
sudo DEBIAN_FRONTEND=noninteractive apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-venv python3-pip ffmpeg unzip curl ca-certificates git

if [ "$ENABLE_2GB" -eq 1 ]; then
    echo "[1b] Docker..."
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io
    if have_systemd; then
        sudo systemctl enable --now docker
    else
        echo "Docker is installed, but without systemd it was not started as a service."
    fi
    if getent group docker >/dev/null 2>&1; then
        sudo usermod -aG docker "$(id -un)"
    fi
fi

echo "[2] venv + pip..."
if [ ! -x "$PROJECT_DIR/venv/bin/python" ]; then
    python3 -m venv "$PROJECT_DIR/venv"
fi
"$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

echo "[3] Deno (as user $(id -un), not root)..."
if [ -x "$HOME/.deno/bin/deno" ] || command -v deno >/dev/null 2>&1; then
    echo "Deno is already installed."
else
    if ! curl -fsSL https://deno.land/install.sh | sh -s -- -y; then
        echo "Warning: Deno install failed. The bot will still run, and yt-dlp will use its built-in JS interpreter."
    fi
fi

if [ "$WRITE_ENV" -eq 1 ]; then
    echo "[4] .env"
    if [ -f .env ]; then
        cp -a .env .env.setup-bak
        echo "Backup: .env.setup-bak"
    fi
    if [ "$KEEP_ENV" -eq 0 ]; then
        old_umask="$(umask)"
        umask 077
        {
            printf 'BOT_TOKEN=%s\n' "$BOT_TOKEN"
            if [ "$ENABLE_2GB" -eq 1 ]; then
                printf 'TELEGRAM_API_ID=%s\n' "$API_ID"
                printf 'TELEGRAM_API_HASH=%s\n' "$API_HASH"
            fi
            printf '\n'
            awk 'BEGIN { p = 0 } /^# Optional: automatic yt-dlp/ { p = 1 } p' .env.example | tr -d '\r'
        } > .env
        umask "$old_umask"
        chmod 600 .env
    else
        upsert_env_key BOT_TOKEN "$BOT_TOKEN"
        upsert_env_key TELEGRAM_API_ID "$API_ID"
        upsert_env_key TELEGRAM_API_HASH "$API_HASH"
    fi
else
    echo "[4] .env left as-is"
fi

if [ "$ENABLE_2GB" -eq 1 ] && have_systemd; then
    echo "[5] systemd..."
    if [ "$START_SERVICES" -eq 1 ]; then
        sudo bash "$PROJECT_DIR/scripts/linux/install_systemd.sh" --start
    else
        sudo bash "$PROJECT_DIR/scripts/linux/install_systemd.sh"
    fi
fi

echo
deno_first_line() {
    local out
    out="$("$1" --version 2>/dev/null || true)"
    printf '%s\n' "${out%%$'\n'*}"
}

echo "Done."
if [ -x "$HOME/.deno/bin/deno" ]; then
    echo "Deno: $(deno_first_line "$HOME/.deno/bin/deno")"
elif command -v deno >/dev/null 2>&1; then
    echo "Deno: $(deno_first_line "$(command -v deno)")"
else
    echo "Deno: not installed"
fi
if command -v ffmpeg >/dev/null 2>&1; then
    echo "FFmpeg: present"
fi

if [ "$ENABLE_2GB" -eq 1 ] && [ "$START_SERVICES" -eq 1 ]; then
    echo "Services started. The first Local API image pull can take a minute."
    echo "  sudo systemctl status tg-bot-ytdl"
    echo "  sudo journalctl -u tg-bot-ytdl -f"
elif [ "$ENABLE_2GB" -eq 0 ]; then
    echo "50MB mode. To start:"
    echo "  bash scripts/linux/run_bot_simple_50MB.sh"
fi

if [ "$ENABLE_2GB" -eq 1 ]; then
    echo "docker without sudo in this shell works only after you log in again (docker group)."
fi
