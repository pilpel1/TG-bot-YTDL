"""המתנה ללייב/פרימיירה של יוטיוב עד שההקלטה ניתנת להורדה.

נשמר ב-data/live_waits.json (אותה תיקייה כמו מצב חיפוש ומנויי ערוצים),
כדי שריסטארט — כולל הכיבוי הלילי של עדכון yt-dlp — לא יאבד את ההמתנה.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import yt_dlp

from config import DATA_DIR, LIVE_WAIT_CHECK_SECONDS, LIVE_WAIT_HOURS
from download_cache import normalize_media_url
from download_manager import download_with_quality
from download_queue import CancellationToken
from logger_setup import logger
from user_settings import remember_chat
from ytdlp_updater import is_maintenance_mode, track_ytdlp_metadata

LIVE_WAITS_FILE = DATA_DIR / 'live_waits.json'

# אחרי הסטטוסים האלה אין עדיין קובץ סופי להוריד.
WAITING_LIVE_STATUSES = frozenset({'is_live', 'is_upcoming', 'post_live'})

_LIVE_PATH_RE = re.compile(r'/live/([^/?#]+)')
_lock = threading.Lock()
_RETRY_WHEN_BUSY_SECONDS = 60


def live_snapshot_from_info(info) -> dict | None:
    """שדות לייב מתוך metadata שכבר נשלף. None אם אין info בכלל."""
    if not info:
        return None
    if info.get('entries'):
        return {
            'probed': True,
            'live_status': None,
            'is_live': False,
            'title': '',
            'video_id': '',
        }
    return {
        'probed': True,
        'live_status': info.get('live_status'),
        'is_live': bool(info.get('is_live')),
        'title': info.get('title') or '',
        'video_id': info.get('id') or '',
    }


def needs_live_wait(live) -> bool:
    """True כשהסרטון עוד לא קובץ שאפשר להוריד (חי / מתוזמן / בעיבוד)."""
    if not live:
        return False
    if live.get('live_status') in WAITING_LIVE_STATUSES:
        return True
    return bool(live.get('is_live'))


def live_reason_he(live) -> str:
    status = (live or {}).get('live_status')
    if status == 'is_upcoming':
        return 'השידור עוד לא התחיל'
    if status == 'post_live':
        return 'השידור נגמר, וההקלטה עוד בעיבוד'
    if status == 'is_live' or (live or {}).get('is_live'):
        return 'השידור עוד חי'
    return 'ההקלטה עוד לא זמינה להורדה'


def check_interval_he() -> str:
    seconds = int(LIVE_WAIT_CHECK_SECONDS)
    if seconds == 3600:
        return 'כל שעה'
    if seconds % 3600 == 0 and seconds > 3600:
        return f'כל {seconds // 3600} שעות'
    if seconds % 60 == 0:
        minutes = seconds // 60
        return 'כל דקה' if minutes == 1 else f'כל {minutes} דקות'
    return f'כל {seconds} שניות'


def format_wait_ack(quality_name: str, live, replaced: bool) -> str:
    lines = []
    if replaced:
        lines.append('כבר עקבתי אחרי הסרטון הזה, אז איפסתי את הספירה.')
    lines.append(f'{live_reason_he(live)}.')
    lines.append(
        f'שמרתי את הבחירה ({quality_name}). '
        f'אבדוק {check_interval_he()}, עד {int(LIVE_WAIT_HOURS)} שעות.'
    )
    lines.append('כשיהיה אפשר להוריד — אוריד. אם לא — אשלח הודעה שקטה.')
    lines.append('/stop מבטל את ההמתנה.')
    return '\n'.join(lines)


def format_live_failure(wait) -> str:
    title = (wait or {}).get('title') or 'הלייב'
    return (
        f'לא הצלחתי להוריד את {title}. '
        f'עברו {int(LIVE_WAIT_HOURS)} שעות וההקלטה לא עלתה.'
    )


def youtube_wait_key(url: str, video_id: str = '') -> str:
    """מפתח יציב לאותו סרטון, גם אם פעם נשלח watch ופעם /live/."""
    video_id = (video_id or '').strip()
    if video_id and video_id != 'playlist':
        return f'youtube:{video_id}'
    key = normalize_media_url(url)
    if key.startswith('youtube:'):
        return key
    match = _LIVE_PATH_RE.search(url or '')
    if match:
        return f'youtube:{match.group(1)}'
    return key or (url or '').strip()


def canonical_watch_url(url: str, video_id: str = '') -> str:
    video_id = (video_id or '').strip()
    if not video_id:
        key = youtube_wait_key(url)
        if key.startswith('youtube:'):
            video_id = key.split(':', 1)[1]
    if video_id and video_id != 'playlist':
        return f'https://www.youtube.com/watch?v={video_id}'
    return url


def serializable_quality(quality) -> dict | None:
    if not isinstance(quality, dict):
        return None
    out = {}
    for key in ('format', 'quality_name', 'download_mode', 'height'):
        if key not in quality:
            continue
        value = quality[key]
        if isinstance(value, bool) or value is None:
            out[key] = value
        elif isinstance(value, (str, int, float)):
            out[key] = value
    if not out.get('format') or not out.get('quality_name'):
        return None
    return out


def _parse_dt(value):
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _now(now=None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current


def _empty_store():
    return {'waits': {}}


def _read() -> dict:
    if not LIVE_WAITS_FILE.exists():
        return _empty_store()
    try:
        with open(LIVE_WAITS_FILE, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get('waits'), dict):
            return data
    except Exception as exc:
        logger.warning(f"Could not read live waits file: {exc}")
    return _empty_store()


def _write(data: dict):
    DATA_DIR.mkdir(exist_ok=True)
    tmp_path = LIVE_WAITS_FILE.with_suffix('.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    tmp_path.replace(LIVE_WAITS_FILE)


def list_live_waits() -> list:
    with _lock:
        waits = _read().get('waits') or {}
        return [dict(item) for item in waits.values()]


def _due_waits(now: datetime) -> list:
    due = []
    for wait in list_live_waits():
        next_check = _parse_dt(wait.get('next_check_at'))
        deadline = _parse_dt(wait.get('deadline_at'))
        if next_check is None or deadline is None:
            due.append(wait)
            continue
        if next_check <= now or deadline <= now:
            due.append(wait)
    return due


def seconds_until_next_live_action(now=None):
    """שניות עד הבדיקה או הדד-ליין הקרובים. None אם אין המתנות."""
    waits = list_live_waits()
    if not waits:
        return None
    current = _now(now)
    soonest = None
    for wait in waits:
        for field in ('next_check_at', 'deadline_at'):
            moment = _parse_dt(wait.get(field))
            if moment is None:
                return 0.0
            if soonest is None or moment < soonest:
                soonest = moment
    if soonest is None:
        return 0.0
    return max(0.0, (soonest - current).total_seconds())


def add_live_wait(chat_id, url, download_mode, quality, live, now=None) -> tuple[dict, bool]:
    """שומר המתנה. אותו צ'אט+סרטון מחליף את הקודמת ומאפס את 48 השעות."""
    current = _now(now)
    snapshot = live or {}
    video_id = snapshot.get('video_id') or ''
    stored_url = canonical_watch_url(url, video_id)
    url_key = youtube_wait_key(stored_url, video_id)
    quality_data = serializable_quality(quality) or {}
    record = {
        'id': uuid.uuid4().hex,
        'chat_id': int(chat_id),
        'url': stored_url,
        'url_key': url_key,
        'download_mode': download_mode,
        'quality': quality_data,
        'title': (snapshot.get('title') or '')[:200],
        'last_live_status': snapshot.get('live_status'),
        'created_at': current.isoformat(),
        'deadline_at': (current + timedelta(hours=int(LIVE_WAIT_HOURS))).isoformat(),
        'next_check_at': (current + timedelta(seconds=int(LIVE_WAIT_CHECK_SECONDS))).isoformat(),
    }
    replaced = False
    with _lock:
        data = _read()
        waits = data.setdefault('waits', {})
        for existing_id, existing in list(waits.items()):
            if (
                str(existing.get('chat_id')) == str(chat_id)
                and existing.get('url_key') == url_key
            ):
                waits.pop(existing_id, None)
                replaced = True
        waits[record['id']] = record
        _write(data)
    logger.info(
        f"Live wait saved chat={chat_id} url={stored_url} "
        f"status={record['last_live_status']} replaced={replaced} "
        f"deadline={record['deadline_at']}"
    )
    return record, replaced


def update_live_wait(wait_id, **fields) -> bool:
    with _lock:
        data = _read()
        waits = data.get('waits') or {}
        record = waits.get(wait_id)
        if not record:
            return False
        record.update(fields)
        _write(data)
        return True


def remove_live_wait(wait_id) -> bool:
    with _lock:
        data = _read()
        waits = data.get('waits') or {}
        if wait_id not in waits:
            return False
        waits.pop(wait_id, None)
        _write(data)
        return True


def cancel_live_waits_for_chat(chat_id) -> int:
    """מוחק המתנות של צ'אט. 0 ולא נוגע בקובץ אם אין מה למחוק."""
    with _lock:
        data = _read()
        waits = data.get('waits') or {}
        removed = [
            wait_id for wait_id, wait in waits.items()
            if str(wait.get('chat_id')) == str(chat_id)
        ]
        if not removed:
            return 0
        for wait_id in removed:
            waits.pop(wait_id, None)
        _write(data)
    logger.info(f"Cancelled {len(removed)} live wait(s) for chat {chat_id}")
    return len(removed)


def probe_youtube_live(url: str) -> dict:
    """extract מלא (לא flat) — live_status אמין רק ככה."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'noplaylist': True,
        'socket_timeout': 30,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    return info


def _is_youtube_single_video(url: str) -> bool:
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or '').lower()
    except Exception:
        return False
    if host.startswith('www.'):
        host = host[4:]
    if host not in {'youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be'}:
        return False
    from utils import is_youtube_playlist_url
    return not is_youtube_playlist_url(url)


async def resolve_live_snapshot(context, url: str):
    """משתמש ב-prefetch שכבר רץ, ורק אם אין — שולף מחדש."""
    task = context.user_data.get('youtube_prefetch_task')
    if task is not None and context.user_data.get('youtube_prefetch_url') == url:
        try:
            result = await task
        except Exception as exc:
            logger.warning(f"YouTube prefetch failed before live check: {exc}")
            result = None
        live = (result or {}).get('live')
        if live and live.get('probed'):
            return live
    try:
        with track_ytdlp_metadata():
            info = await asyncio.to_thread(probe_youtube_live, url)
        return live_snapshot_from_info(info)
    except Exception as exc:
        logger.warning(f"Live probe failed for {url}: {exc}")
        return None


def _wake_manager(context):
    bot_data = getattr(context, 'bot_data', None)
    if not isinstance(bot_data, dict):
        return
    manager = bot_data.get('live_wait')
    if manager is not None:
        manager.wake()


async def maybe_register_live_wait(message, context, url, download_mode, quality) -> bool:
    """True אם נשמרה המתנה ואין להוריד עכשיו.

    כישלון בדיקה לא חוסם הורדה רגילה — עדיף לנסות מאשר לבלוע סרטון רגיל.
    """
    if not _is_youtube_single_video(url):
        return False
    if serializable_quality(quality) is None:
        return False

    live = await resolve_live_snapshot(context, url)
    if not needs_live_wait(live):
        return False

    record, replaced = add_live_wait(
        message.chat_id,
        url,
        download_mode,
        quality,
        live,
    )
    text = format_wait_ack(record['quality']['quality_name'], live, replaced)
    try:
        await message.edit_text(text)
    except Exception as exc:
        logger.warning(f"Could not edit live-wait ack: {exc}")
        try:
            await message.reply_text(text)
        except Exception as reply_exc:
            logger.warning(f"Could not send live-wait ack: {reply_exc}")
    remember_chat(message.chat_id, chat=getattr(message, 'chat', None))
    _wake_manager(context)
    return True


class _DownloadContext:
    """context מינימלי ל-download_with_quality כשההורדה לא הגיעה מ-handler."""

    def __init__(self, bot_data):
        self.bot_data = bot_data
        self.user_data = {}


class LiveWaitManager:
    """טאסק רקע: ישן עד הבדיקה הבאה, ואם ההקלטה עלתה — מכניס לתור."""

    def __init__(self, application):
        self._application = application
        self._task = None
        self._wake = asyncio.Event()

    def wake(self):
        self._wake.set()

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._scheduler_loop())
            pending = len(list_live_waits())
            logger.info(f"Live wait scheduler started ({pending} pending)")

    async def stop(self):
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _scheduler_loop(self):
        try:
            while True:
                self._wake.clear()
                delay = seconds_until_next_live_action()
                if delay is None:
                    await self._wake.wait()
                    continue
                if delay > 0:
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        pass
                    continue
                try:
                    ran = await self.run_due()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error(f"Live wait check failed: {exc}")
                    ran = False
                if not ran:
                    await asyncio.sleep(_RETRY_WHEN_BUSY_SECONDS)
        except asyncio.CancelledError:
            logger.info("Live wait task cancelled")
            raise

    async def run_due(self, now=None) -> bool:
        """מעבד המתנות שהגיע זמנן. False = דילוג (תחזוקה), בלי להזיז דד-ליין."""
        if is_maintenance_mode():
            logger.info("Skipping live wait check: maintenance mode")
            return False

        current = _now(now)
        for wait in _due_waits(current):
            await self._process_wait(wait, current)
        return True

    async def _process_wait(self, wait, now: datetime):
        deadline = _parse_dt(wait.get('deadline_at'))
        if deadline is None:
            logger.warning(f"Dropping live wait with bad deadline: {wait.get('id')}")
            remove_live_wait(wait.get('id'))
            return

        expired = deadline <= now
        try:
            with track_ytdlp_metadata():
                info = await asyncio.to_thread(probe_youtube_live, wait['url'])
            live = live_snapshot_from_info(info)
        except Exception as exc:
            logger.warning(f"Live recheck failed for {wait.get('url')}: {exc}")
            live = None

        if not live:
            if expired:
                await self._fail(wait)
            else:
                self._postpone(wait, now)
            return

        if not needs_live_wait(live):
            await self._begin_download(wait, live)
            return
        if expired:
            await self._fail(wait)
            return
        self._postpone(wait, now, live_status=(live or {}).get('live_status'))

    def _postpone(self, wait, now: datetime, live_status=None, seconds=None):
        deadline = _parse_dt(wait.get('deadline_at'))
        interval = int(LIVE_WAIT_CHECK_SECONDS if seconds is None else seconds)
        next_at = now + timedelta(seconds=max(1, interval))
        if deadline is not None and next_at > deadline:
            next_at = deadline
        fields = {'next_check_at': next_at.isoformat()}
        if live_status is not None:
            fields['last_live_status'] = live_status
        update_live_wait(wait['id'], **fields)
        logger.info(
            f"Live wait still pending chat={wait.get('chat_id')} "
            f"url={wait.get('url')} next={fields['next_check_at']}"
        )

    async def _fail(self, wait):
        remove_live_wait(wait['id'])
        chat_id = wait.get('chat_id')
        try:
            await self._application.bot.send_message(
                chat_id=int(chat_id),
                text=format_live_failure(wait),
                disable_notification=True,
            )
        except Exception as exc:
            logger.warning(f"Could not send silent live-wait failure to {chat_id}: {exc}")
        logger.info(f"Live wait expired chat={chat_id} url={wait.get('url')}")

    async def _begin_download(self, wait, live):
        queue = self._application.bot_data.get('download_queue')
        if queue is None:
            logger.warning("Live recording is ready but download queue is missing; will retry")
            self._postpone(wait, _now(), seconds=_RETRY_WHEN_BUSY_SECONDS)
            return

        chat_id = int(wait['chat_id'])
        title = (live or {}).get('title') or wait.get('title') or ''
        if title and title != wait.get('title'):
            update_live_wait(wait['id'], title=title[:200])
        try:
            remember_chat(chat_id)
            status_message = await self._application.bot.send_message(
                chat_id=chat_id,
                text='ההקלטה עלתה. מוריד... ⏳',
            )
        except Exception as exc:
            logger.warning(f"Could not announce ready live to {chat_id}: {exc}")
            self._postpone(wait, _now(), seconds=_RETRY_WHEN_BUSY_SECONDS)
            return

        cancel_token = CancellationToken()
        context = _DownloadContext(self._application.bot_data)
        url = wait['url']
        download_mode = wait.get('download_mode')
        quality = wait.get('quality') or {}

        async def run_download():
            await download_with_quality(
                context,
                status_message,
                url,
                download_mode,
                quality,
                None,
                should_cancel=cancel_token.is_cancelled,
            )

        await queue.enqueue(
            chat_id=chat_id,
            status_message=status_message,
            coro_factory=run_download,
            weight=1,
            cancel_token=cancel_token,
        )
        remove_live_wait(wait['id'])
        logger.info(f"Live recording queued chat={chat_id} url={url}")
