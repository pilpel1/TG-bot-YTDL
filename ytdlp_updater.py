"""בדיקת גרסת yt-dlp, מצב תחזוקה, וכיבוי נקי לפני התקנה ב-wrapper."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yt_dlp

from config import (
    MAINTENANCE_USER_MESSAGE,
    VERSION,
    YTDLP_PENDING_UPDATE_FLAG,
    YTDLP_UPDATE_HOUR,
    YTDLP_UPDATE_MAX_WAIT_HOURS,
    YTDLP_UPDATE_TIMEZONE,
)
from logger_setup import logger

PYPI_YTDLP_JSON_URL = 'https://pypi.org/pypi/yt-dlp/json'
_IDLE_POLL_SECONDS = 2
_POST_TIMEOUT_GRACE_SECONDS = 60

_maintenance_active = False
_metadata_inflight = 0


def is_maintenance_mode() -> bool:
    return _maintenance_active


def set_maintenance_mode(active: bool) -> None:
    global _maintenance_active
    active = bool(active)
    if _maintenance_active == active:
        return
    _maintenance_active = active
    logger.info(f"Maintenance mode {'ON' if _maintenance_active else 'OFF'}")


def has_inflight_metadata() -> bool:
    return _metadata_inflight > 0


@contextmanager
def track_ytdlp_metadata():
    """סופר שליפות yt-dlp ברקע (prefetch/חיפוש) כדי לא לכבות באמצען."""
    global _metadata_inflight
    _metadata_inflight += 1
    try:
        yield
    finally:
        _metadata_inflight = max(0, _metadata_inflight - 1)


def get_installed_ytdlp_version() -> str:
    return yt_dlp.version.__version__


def parse_ytdlp_version(version: str) -> tuple:
    """2026.8.19 / 2026.08.19.233646 → tuple של מספרים להשוואה."""
    parts = []
    for piece in (version or '').split('.'):
        try:
            parts.append(int(piece))
        except ValueError:
            break
    return tuple(parts)


def is_newer_ytdlp_version(latest: str, installed: str) -> bool:
    latest_parts = parse_ytdlp_version(latest)
    installed_parts = parse_ytdlp_version(installed)
    if not latest_parts:
        return False
    return latest_parts > installed_parts


def fetch_latest_ytdlp_version(timeout=30) -> str:
    """אותו אינדקס ש-pip משתמש בו (PyPI)."""
    response = requests.get(
        PYPI_YTDLP_JSON_URL,
        timeout=timeout,
        headers={'User-Agent': f'TG-bot-YTDL/{VERSION}'},
    )
    response.raise_for_status()
    version = response.json().get('info', {}).get('version')
    if not version:
        raise ValueError('PyPI response did not include yt-dlp version')
    return version


def write_pending_update_flag(latest_version: str, flag_path: Path = None) -> Path:
    path = Path(flag_path) if flag_path is not None else YTDLP_PENDING_UPDATE_FLAG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{latest_version}\n', encoding='utf-8')
    logger.info(f"Wrote pending yt-dlp update flag ({latest_version}) to {path}")
    return path


def get_update_timezone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(YTDLP_UPDATE_TIMEZONE)
    except Exception as e:
        logger.warning(
            f"Timezone {YTDLP_UPDATE_TIMEZONE!r} unavailable ({e}); "
            "falling back to server local time"
        )
        return datetime.now().astimezone().tzinfo or timezone.utc


def seconds_until_next_check(now: datetime = None) -> float:
    tz = get_update_timezone()
    if now is None:
        now = datetime.now(tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)

    target = now.replace(hour=YTDLP_UPDATE_HOUR, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return max(0.0, (target - now).total_seconds())


class YtdlpUpdateManager:
    """משימת רקע: פעם ביום בודקת גרסה. אם יש חדשה — תחזוקה, המתנה, כיבוי."""

    def __init__(self, application):
        self._application = application
        self._task = None

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._scheduler_loop())
            logger.info(
                "yt-dlp updater started "
                f"(hour={YTDLP_UPDATE_HOUR:02d}:00, tz={YTDLP_UPDATE_TIMEZONE}, "
                f"max_wait_hours={YTDLP_UPDATE_MAX_WAIT_HOURS})"
            )

    async def stop(self):
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        set_maintenance_mode(False)

    async def _scheduler_loop(self):
        try:
            while True:
                delay = seconds_until_next_check()
                hours = delay / 3600
                logger.info(
                    f"Next yt-dlp version check in {hours:.1f} hours "
                    f"({YTDLP_UPDATE_HOUR:02d}:00 {YTDLP_UPDATE_TIMEZONE})"
                )
                await asyncio.sleep(delay)
                try:
                    await self.run_check()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"yt-dlp version check failed: {e}")
        except asyncio.CancelledError:
            logger.info("yt-dlp updater task cancelled")
            raise

    async def run_check(self):
        installed = get_installed_ytdlp_version()
        logger.info(f"yt-dlp version check started; installed={installed}")
        try:
            latest = fetch_latest_ytdlp_version()
        except Exception as e:
            logger.warning(f"Could not fetch latest yt-dlp version from PyPI: {e}")
            return False

        logger.info(f"yt-dlp on PyPI: latest={latest}")
        if not is_newer_ytdlp_version(latest, installed):
            logger.info("yt-dlp is up to date; bot stays running")
            return False

        logger.info(f"New yt-dlp available: {installed} -> {latest}")
        await self._enter_maintenance_and_restart(latest)
        return True

    async def _enter_maintenance_and_restart(self, latest_version: str):
        set_maintenance_mode(True)
        queue = self._application.bot_data.get('download_queue')
        deadline = asyncio.get_running_loop().time() + (
            YTDLP_UPDATE_MAX_WAIT_HOURS * 3600
        )

        logger.info("Waiting for download queue and metadata fetches to go idle")
        last_status_log = 0.0
        while True:
            loop_time = asyncio.get_running_loop().time()
            idle = (queue is None or queue.is_idle()) and not has_inflight_metadata()
            if idle:
                logger.info("Bot is idle; proceeding with yt-dlp update shutdown")
                break

            jobs = queue.job_count() if queue is not None else 0
            remaining = deadline - loop_time
            if remaining <= 0:
                logger.warning(
                    f"Idle wait timed out after {YTDLP_UPDATE_MAX_WAIT_HOURS} hours "
                    f"(jobs={jobs}, metadata_inflight={_metadata_inflight}); "
                    "cancelling remaining jobs"
                )
                if queue is not None:
                    cancelled = await queue.cancel_all(MAINTENANCE_USER_MESSAGE)
                    logger.warning(f"Cancelled {cancelled} jobs after maintenance timeout")
                grace_until = asyncio.get_running_loop().time() + _POST_TIMEOUT_GRACE_SECONDS
                while asyncio.get_running_loop().time() < grace_until:
                    if (queue is None or queue.is_idle()) and not has_inflight_metadata():
                        break
                    await asyncio.sleep(_IDLE_POLL_SECONDS)
                break

            if loop_time - last_status_log >= 300:
                logger.info(
                    f"Still waiting for idle: jobs={jobs}, "
                    f"metadata_inflight={_metadata_inflight}, "
                    f"{remaining / 60:.0f} minutes left"
                )
                last_status_log = loop_time
            await asyncio.sleep(_IDLE_POLL_SECONDS)

        write_pending_update_flag(latest_version)
        logger.info("Stopping bot so the service wrapper can install yt-dlp")
        self._application.stop_running()
