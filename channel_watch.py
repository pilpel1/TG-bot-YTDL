"""מעקב ערוצי יוטיוב: גילוי סרטונים חדשים + cron פנימי.

הלוגיקה הושאלה מה-skill החיצוני (poll זול / baseline ראשון / last_seen
לכל source / notified_video_ids), בלי LLM ובלי cron של המכונה.
"""
from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs

import yt_dlp

from config import (
    CHANNEL_WATCH_FETCH_LIMIT,
    CHANNEL_WATCH_HOURS,
    CHANNEL_WATCH_TIMEZONE,
    YOUTUBE_QUALITY_LEVELS,
)
from download_manager import download_with_quality
from download_queue import CancellationToken
from logger_setup import logger
from user_settings import (
    get_channel_watch_last_run,
    iter_all_channel_subs,
    set_channel_watch_last_run,
    update_channel_sub,
)
from utils import build_youtube_audio_option
from ytdlp_updater import is_maintenance_mode, track_ytdlp_metadata

CHANNEL_TAB_SUFFIXES = (
    'videos', 'shorts', 'streams', 'playlists', 'community',
    'featured', 'about', 'podcasts',
)

YOUTUBE_HOSTS = {
    'youtube.com', 'www.youtube.com', 'm.youtube.com',
    'music.youtube.com', 'youtu.be', 'www.youtu.be',
}

FIXED_VIDEO_QUALITY = YOUTUBE_QUALITY_LEVELS[1]


def get_watch_timezone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(CHANNEL_WATCH_TIMEZONE)
    except Exception as e:
        logger.warning(
            f"Timezone {CHANNEL_WATCH_TIMEZONE!r} unavailable ({e}); "
            "falling back to server local time"
        )
        return datetime.now().astimezone().tzinfo or timezone.utc


def _aware(now: datetime = None) -> datetime:
    tz = get_watch_timezone()
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def scheduled_slots_on_day(day: datetime):
    """כל השעות המתוזמנות באותו יום מקומי, ממוינות."""
    return [
        day.replace(hour=hour, minute=0, second=0, microsecond=0)
        for hour in CHANNEL_WATCH_HOURS
    ]


def most_recent_watch_slot(now: datetime = None):
    """החלון האחרון שכבר הגיע (כולל הרגע הזה). None אם אין שעות."""
    if not CHANNEL_WATCH_HOURS:
        return None
    now = _aware(now)
    today_slots = scheduled_slots_on_day(now)
    past = [slot for slot in today_slots if slot <= now]
    if past:
        return past[-1]
    yesterday = now - timedelta(days=1)
    return scheduled_slots_on_day(yesterday)[-1]


def next_watch_slot(now: datetime = None):
    if not CHANNEL_WATCH_HOURS:
        return None
    now = _aware(now)
    for slot in scheduled_slots_on_day(now):
        if slot > now:
            return slot
    tomorrow = now + timedelta(days=1)
    return scheduled_slots_on_day(tomorrow)[0]


def seconds_until_next_watch(now: datetime = None, last_run_at=None) -> float:
    """כמה לישון עד הבדיקה הבאה. 0 = לרוץ עכשיו (פספסנו חלון).

    בלי last_run (עלייה ראשונה) — לא רצים מיד, רק מחכים לחלון הבא.
    אם last_run קדם לחלון האחרון שכבר הגיע — רצים עכשיו.
    """
    if not CHANNEL_WATCH_HOURS:
        return 24 * 3600
    now = _aware(now)
    last_run = parse_iso_datetime(last_run_at)
    recent = most_recent_watch_slot(now)
    if last_run is not None and recent is not None and last_run < recent:
        return 0.0
    upcoming = next_watch_slot(now)
    if upcoming is None:
        return 24 * 3600
    return max(0.0, (upcoming - now).total_seconds())


def is_youtube_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or '').lower()
    except Exception:
        return False
    if host.startswith('www.'):
        host = host[4:]
    return host in {h[4:] if h.startswith('www.') else h for h in YOUTUBE_HOSTS} or host in YOUTUBE_HOSTS


def _strip_channel_tab(path: str) -> str:
    parts = [part for part in path.split('/') if part]
    if parts and parts[-1].lower() in CHANNEL_TAB_SUFFIXES:
        parts = parts[:-1]
    return '/' + '/'.join(parts) if parts else '/'


def normalize_youtube_channel_url(url: str):
    """מחזיר URL קנוני לערוץ, או None אם זה לא קישור-ערוץ מזוהה."""
    if not url or not is_youtube_url(url):
        return None
    parsed = urlparse(url.strip())
    host = (parsed.hostname or '').lower()
    path = parsed.path or '/'

    if host in ('youtu.be', 'www.youtu.be'):
        return None

    path = _strip_channel_tab(path)
    parts = [part for part in path.split('/') if part]
    if not parts:
        return None

    if parts[0].startswith('@') and len(parts) == 1:
        handle = parts[0]
        return f'https://www.youtube.com/{handle}'
    if parts[0] == 'channel' and len(parts) >= 2:
        return f'https://www.youtube.com/channel/{parts[1]}'
    if parts[0] == 'c' and len(parts) >= 2:
        return f'https://www.youtube.com/c/{parts[1]}'
    if parts[0] == 'user' and len(parts) >= 2:
        return f'https://www.youtube.com/user/{parts[1]}'
    return None


def is_youtube_video_url(url: str) -> bool:
    if not url or not is_youtube_url(url):
        return False
    parsed = urlparse(url.strip())
    host = (parsed.hostname or '').lower()
    path = parsed.path or ''
    query = parse_qs(parsed.query)
    if host in ('youtu.be', 'www.youtu.be') and path.strip('/'):
        return True
    if query.get('v'):
        return True
    if '/shorts/' in path or '/live/' in path or '/embed/' in path:
        return True
    return False


def source_tab_url(channel_url: str, source_key: str) -> str:
    return f"{channel_url.rstrip('/')}/{source_key}"


def _ydl_flat_opts():
    return {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'skip_download': True,
        'socket_timeout': 30,
    }


def resolve_channel(url: str) -> dict:
    """מזהה ערוץ מקישור ערוץ או מקישור סרטון. זורק אם נכשל."""
    channel_url = normalize_youtube_channel_url(url)
    lookup_url = channel_url or url
    with yt_dlp.YoutubeDL(_ydl_flat_opts()) as ydl:
        info = ydl.extract_info(lookup_url, download=False)

    if not info:
        raise ValueError('Could not resolve channel')

    resolved_url = (
        normalize_youtube_channel_url(info.get('channel_url') or '')
        or normalize_youtube_channel_url(info.get('uploader_url') or '')
        or channel_url
        or normalize_youtube_channel_url(info.get('webpage_url') or '')
    )
    label = (
        info.get('channel')
        or info.get('uploader')
        or info.get('title')
        or resolved_url
        or url
    )
    channel_id = info.get('channel_id') or info.get('uploader_id') or ''
    if not resolved_url:
        raise ValueError('Could not resolve channel url')
    return {
        'channel_url': resolved_url,
        'channel_id': channel_id,
        'channel_label': str(label).strip() or resolved_url,
    }


def fetch_source_entries(channel_url: str, source_key: str, limit: int = None):
    limit = limit or CHANNEL_WATCH_FETCH_LIMIT
    tab_url = source_tab_url(channel_url, source_key)
    opts = _ydl_flat_opts()
    opts['playlistend'] = limit
    with yt_dlp.YoutubeDL(opts) as ydl:
        data = ydl.extract_info(tab_url, download=False)

    entries = []
    if not data:
        return entries
    for item in data.get('entries') or []:
        if not isinstance(item, dict):
            continue
        video_id = item.get('id')
        if not video_id:
            continue
        raw_url = item.get('url') or item.get('webpage_url') or ''
        if not raw_url.startswith('http'):
            raw_url = f'https://www.youtube.com/watch?v={video_id}'
        entries.append({
            'video_id': video_id,
            'title': item.get('title') or '',
            'url': raw_url,
            'source': source_key,
        })
    return entries


def get_video_metadata(url: str) -> dict:
    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'socket_timeout': 30,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False) or {}


def find_new_entries(entries, last_seen_video_id):
    """כל הפריטים מעל last_seen, מהחדש לישן כמו ב-yt-dlp. ריק אם אין חדש."""
    if not entries:
        return []
    if not last_seen_video_id:
        return []
    new_entries = []
    for entry in entries:
        if entry['video_id'] == last_seen_video_id:
            break
        new_entries.append(entry)
    return new_entries


def initialize_baselines(sub: dict, source_entries: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    sub['initialized_at'] = sub.get('initialized_at') or now
    for source_key, entries in source_entries.items():
        src_state = sub['sources_state'].setdefault(source_key, {
            'last_seen_video_id': None,
            'last_seen_title': None,
        })
        if entries:
            src_state['last_seen_video_id'] = entries[0]['video_id']
            src_state['last_seen_title'] = entries[0]['title']
    return sub


def summarize_description_fallback(description: str, max_chars: int = 320) -> str:
    if not description:
        return ''
    cleaned_lines = []
    for raw in description.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r'https?://\S+', line):
            continue
        if line.lower().startswith(('http://', 'https://')):
            continue
        cleaned_lines.append(line)
    if not cleaned_lines:
        return ''
    text = ' '.join(cleaned_lines)
    text = re.sub(r'https?://\S+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip(' -—|•\t')
    if not text:
        return ''
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(' ', 1)[0].strip()
    if not cut:
        cut = text[:max_chars].strip()
    return cut.rstrip(' ,;:-') + '…'


def html_link(url: str, text: str) -> str:
    safe_text = html.escape(text or url or '')
    safe_url = html.escape(url or '', quote=True)
    return f'<a href="{safe_url}">{safe_text}</a>'


def format_new_video_html(channel_label, channel_url, title, video_url, description=None) -> str:
    message = (
        f'ערוץ {html_link(channel_url, channel_label)} העלה סרטון חדש: '
        f'{html_link(video_url, title)}'
    )
    if description:
        message += f'\n\n{html.escape(description)}'
    return message


def sources_label_he(sources) -> str:
    sources = list(sources or [])
    has_videos = 'videos' in sources
    has_shorts = 'shorts' in sources
    if has_videos and has_shorts:
        return 'סרטונים + שורטס'
    if has_shorts:
        return 'שורטס'
    return 'סרטונים'


def delivery_label_he(delivery) -> str:
    delivery = list(delivery or [])
    has_audio = 'audio' in delivery
    has_video = 'video' in delivery
    if has_audio and has_video:
        return 'אודיו + וידאו'
    if has_video:
        return 'וידאו'
    return 'אודיו'


def description_label_he(include_description: bool) -> str:
    return 'עם תיאור' if include_description else 'בלי תיאור'


class _DownloadContext:
    """context מינימלי ל-download_with_quality כשההורדה לא הגיעה מ-handler."""

    def __init__(self, bot_data):
        self.bot_data = bot_data
        self.user_data = {}


async def deliver_new_video(application, chat_id, sub, entry):
    video_url = entry.get('url') or f"https://www.youtube.com/watch?v={entry['video_id']}"
    title = entry.get('title') or 'סרטון חדש'
    description = None
    if sub.get('include_description'):
        try:
            with track_ytdlp_metadata():
                metadata = await asyncio.to_thread(get_video_metadata, video_url)
            title = metadata.get('title') or title
            description = summarize_description_fallback(metadata.get('description') or '')
        except Exception as e:
            logger.warning(f"Could not fetch metadata for {video_url}: {e}")

    announcement = format_new_video_html(
        sub.get('channel_label') or 'ערוץ',
        sub.get('channel_url') or video_url,
        title,
        video_url,
        description,
    )
    await application.bot.send_message(
        chat_id=int(chat_id),
        text=announcement,
        parse_mode='HTML',
        disable_web_page_preview=True,
    )

    if is_maintenance_mode():
        logger.info("Skipped channel-watch download enqueue: maintenance mode")
        return

    queue = application.bot_data.get('download_queue')
    if not queue:
        logger.warning("No download queue; skipped media for channel watch")
        return

    delivery = sub.get('delivery') or ['audio']
    status_message = await application.bot.send_message(
        chat_id=int(chat_id),
        text='מוריד את הסרטון החדש... ⏳',
    )
    cancel_token = CancellationToken()
    context = _DownloadContext(application.bot_data)

    async def run_delivery():
        for mode in delivery:
            if cancel_token.is_cancelled():
                return
            quality = build_youtube_audio_option() if mode == 'audio' else FIXED_VIDEO_QUALITY
            await download_with_quality(
                context,
                status_message,
                video_url,
                mode,
                quality,
                None,
                should_cancel=cancel_token.is_cancelled,
                quiet_complete=True,
            )

    await queue.enqueue(
        chat_id=int(chat_id),
        status_message=status_message,
        coro_factory=lambda: run_delivery(),
        weight=max(1, len(delivery)),
        cancel_token=cancel_token,
    )


def check_subscription_for_new_videos(sub: dict):
    """מחזיר (updated_sub, new_entries). בלי שליחה."""
    notified = set(sub.get('notified_video_ids') or [])
    new_entries = []
    for source_key in sub.get('sources') or ['videos']:
        try:
            with track_ytdlp_metadata():
                entries = fetch_source_entries(sub['channel_url'], source_key)
        except Exception as e:
            logger.warning(
                f"Channel watch fetch failed for {sub.get('channel_label')} "
                f"/{source_key}: {e}"
            )
            continue

        src_state = sub['sources_state'].setdefault(source_key, {
            'last_seen_video_id': None,
            'last_seen_title': None,
        })
        if not entries:
            continue

        last_seen = src_state.get('last_seen_video_id')
        if not last_seen:
            src_state['last_seen_video_id'] = entries[0]['video_id']
            src_state['last_seen_title'] = entries[0]['title']
            continue

        found = find_new_entries(entries, last_seen)
        src_state['last_seen_video_id'] = entries[0]['video_id']
        src_state['last_seen_title'] = entries[0]['title']
        for entry in reversed(found):
            if entry['video_id'] in notified:
                continue
            new_entries.append(entry)
            notified.add(entry['video_id'])

    sub['notified_video_ids'] = list(notified)
    return sub, new_entries


class ChannelWatchManager:
    """טאסק רקע: ישן עד השעה הבאה, בודק ערוצים, מכניס הורדות לתור."""

    def __init__(self, application):
        self._application = application
        self._task = None

    def start(self):
        if not CHANNEL_WATCH_HOURS:
            logger.info("Channel watch disabled (CHANNEL_WATCH_HOURS is empty)")
            return
        if self._task is None:
            self._task = asyncio.create_task(self._scheduler_loop())
            hours = ','.join(f'{hour:02d}:00' for hour in CHANNEL_WATCH_HOURS)
            logger.info(
                f"Channel watch started (hours={hours}, tz={CHANNEL_WATCH_TIMEZONE})"
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

    async def _scheduler_loop(self):
        try:
            while True:
                delay = seconds_until_next_watch(last_run_at=get_channel_watch_last_run())
                if delay > 0:
                    hours = delay / 3600
                    logger.info(f"Next channel watch check in {hours:.1f} hours")
                    await asyncio.sleep(delay)
                try:
                    await self.run_check()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Channel watch check failed: {e}")
                    set_channel_watch_last_run(datetime.now(timezone.utc).isoformat())
        except asyncio.CancelledError:
            logger.info("Channel watch task cancelled")
            raise

    async def run_check(self):
        if is_maintenance_mode():
            logger.info("Skipping channel watch check: maintenance mode")
            return False

        items = iter_all_channel_subs()
        logger.info(f"Channel watch check started ({len(items)} subscriptions)")
        delivered = 0
        for user_id, index, sub in items:
            try:
                updated, new_entries = await asyncio.to_thread(
                    check_subscription_for_new_videos, sub
                )
                update_channel_sub(
                    user_id,
                    index,
                    sources_state=updated.get('sources_state'),
                    notified_video_ids=updated.get('notified_video_ids'),
                )
                for entry in new_entries:
                    await deliver_new_video(self._application, user_id, updated, entry)
                    delivered += 1
            except Exception as e:
                logger.error(
                    f"Channel watch failed for user {user_id} "
                    f"{sub.get('channel_label')}: {e}"
                )

        set_channel_watch_last_run(datetime.now(timezone.utc).isoformat())
        logger.info(f"Channel watch check finished; delivered={delivered}")
        return True
