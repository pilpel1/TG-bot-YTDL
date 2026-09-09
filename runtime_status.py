"""סטטוס ריצה לאדמין: uptime, קומיט שנטען בתהליך, מצב תור."""
from __future__ import annotations

import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from config import LOCAL_API_AVAILABLE, MAX_FILE_SIZE, VERSION
from logger_setup import logger
from ytdlp_updater import get_installed_ytdlp_version, is_maintenance_mode

DOCKER_API_CONTAINER = 'telegram-bot-api'
# אחרי תו לטיני, ספרה נדבקת ל-LTR. RLM מחזיר את המספר לכיוון העברי.
RLM = '\u200f'

REPO_ROOT = Path(__file__).resolve().parent

# נקבע ב-mark_runtime_start() בתחילת התהליך. קומיט נשמר פעם אחת —
# אחרת git pull בלי ריסטארט היה מציג HEAD חדש על קוד ישן שעדיין בזיכרון.
_started_monotonic = time.monotonic()
_git_info: dict | None = None


def mark_runtime_start(repo_root: Path | None = None):
    """קוראים פעם אחת בעליית התהליך, לפני polling."""
    global _started_monotonic, _git_info
    _started_monotonic = time.monotonic()
    _git_info = read_git_info(repo_root)
    git = _git_info
    extra = ' dirty' if git.get('dirty') else ''
    logger.info(
        f"Runtime git: {git.get('hash') or '?'}{extra} {git.get('subject') or ''}".strip()
    )


def get_service_uptime_seconds() -> float:
    return time.monotonic() - _started_monotonic


def get_host_uptime_seconds() -> float | None:
    try:
        with open('/proc/uptime', encoding='ascii') as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    try:
        import ctypes
        return ctypes.windll.kernel32.GetTickCount64() / 1000.0
    except Exception:
        return None


def parse_docker_started_at(value: str, now: Optional[datetime] = None) -> float | None:
    """מפרסר StartedAt של docker (RFC3339 עם ננו-שניות ו-Z) ל-uptime בשניות."""
    text = (value or '').strip()
    if not text or text.startswith('0001-01-01'):
        return None
    tz = timezone.utc
    if text.endswith('Z'):
        text = text[:-1]
    elif len(text) >= 6 and (text[-6] in '+-') and text[-3] == ':':
        sign = 1 if text[-6] == '+' else -1
        try:
            off_h = int(text[-5:-3])
            off_m = int(text[-2:])
        except ValueError:
            return None
        tz = timezone(sign * timedelta(hours=off_h, minutes=off_m))
        text = text[:-6]
    if '.' in text:
        main, frac = text.split('.', 1)
        digits = ''.join(c for c in frac if c.isdigit())[:6].ljust(6, '0')
        text = f'{main}.{digits}'
        fmt = '%Y-%m-%dT%H:%M:%S.%f'
    else:
        fmt = '%Y-%m-%dT%H:%M:%S'
    try:
        started = datetime.strptime(text, fmt).replace(tzinfo=tz)
    except ValueError:
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0.0, (current - started.astimezone(timezone.utc)).total_seconds())


def get_docker_api_status(container_name: str = DOCKER_API_CONTAINER) -> dict:
    """שואל את docker על קונטיינר Local API. חי בכל /status, לא בעלייה."""
    empty = {
        'found': False,
        'running': False,
        'uptime_seconds': None,
        'status': None,
        'error': 'failed',
    }
    try:
        result = subprocess.run(
            [
                'docker', 'inspect',
                '--format', '{{.State.Running}}\t{{.State.Status}}\t{{.State.StartedAt}}',
                container_name,
            ],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=2,
            check=False,
        )
    except FileNotFoundError:
        empty['error'] = 'no_docker'
        return empty
    except subprocess.TimeoutExpired:
        empty['error'] = 'timeout'
        return empty
    except OSError:
        empty['error'] = 'no_docker'
        return empty

    stderr = (result.stderr or '').lower()
    if result.returncode != 0:
        if 'permission denied' in stderr or 'access is denied' in stderr:
            empty['error'] = 'permission'
        elif 'no such object' in stderr or 'no such container' in stderr:
            empty['error'] = 'not_found'
        elif 'cannot connect' in stderr or 'docker daemon' in stderr:
            empty['error'] = 'daemon'
        return empty

    parts = (result.stdout or '').strip().split('\t')
    if len(parts) < 3:
        return empty
    running = parts[0].strip().lower() == 'true'
    status = parts[1].strip() or None
    uptime = parse_docker_started_at(parts[2]) if running else None
    return {
        'found': True,
        'running': running,
        'uptime_seconds': uptime,
        'status': status,
        'error': None,
    }


def _docker_line(rest: str) -> str:
    """'ה-Docker:' + RLM כדי שהמספר אחרי הלעז יישאר ב-RTL."""
    return f'ה-Docker:{RLM} {rest}'


def format_docker_line(docker_status: dict | None) -> str | None:
    """שורה אחת ל-/status. מתחילה בעברית כדי שטלגרם לא יהפוך RTL."""
    if not docker_status:
        return None
    err = docker_status.get('error')
    if err == 'no_docker':
        return _docker_line('לא מותקן')
    if err == 'permission':
        return _docker_line('אין הרשאה')
    if err == 'timeout':
        return _docker_line('אין תשובה')
    if err == 'daemon':
        return _docker_line('לא זמין')
    if err == 'failed':
        return _docker_line('לא זמין')
    if err == 'not_found' or not docker_status.get('found'):
        return _docker_line('אין קונטיינר')
    if docker_status.get('running'):
        return _docker_line(format_duration_he(docker_status.get('uptime_seconds')))
    status = docker_status.get('status') or 'לא רץ'
    return _docker_line(f'לא רץ ({status})')


def read_git_info(repo_root: Path | None = None) -> dict:
    root = repo_root or REPO_ROOT
    info = {'hash': None, 'subject': None, 'dirty': False}
    short = _git_output(['rev-parse', '--short', 'HEAD'], root)
    if not short:
        return info
    info['hash'] = short
    info['subject'] = _git_output(['log', '-1', '--format=%B'], root)
    dirty = _git_output(['status', '--porcelain'], root)
    info['dirty'] = bool(dirty)
    return info


def get_git_info() -> dict:
    global _git_info
    if _git_info is None:
        _git_info = read_git_info()
    return _git_info


def _git_output(args: list[str], repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ['git', *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or '').strip() or None


def format_duration_he(seconds) -> str:
    if seconds is None:
        return 'לא ידוע'
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append('1 יום' if days == 1 else f'{days} ימים')
    if hours:
        parts.append('1 שעה' if hours == 1 else f'{hours} שעות')
    if minutes:
        parts.append('1 דקה' if minutes == 1 else f'{minutes} דקות')
    if not parts:
        parts.append('1 שנייה' if secs == 1 else f'{secs} שניות')
    return ', '.join(parts)


def format_file_limit_line(max_file_size: int, local_api: bool) -> str:
    gb = max_file_size / (1024 * 1024 * 1024)
    mb = max_file_size / (1024 * 1024)
    if gb >= 1:
        return f'קבצים: עד {gb:.1f}GB' + (' (Local API)' if local_api else '')
    return f'קבצים: עד {mb:.0f}MB' + (' (Telegram רגיל)' if not local_api else '')


def format_queue_lines(snapshot: dict) -> list[str]:
    running = snapshot.get('running')
    waiting = int(snapshot.get('waiting') or 0)
    elapsed = snapshot.get('running_elapsed')
    if not running and waiting == 0:
        return ['תור: פנוי']
    lines = []
    if running:
        lines.append(f'תור: הורדה פעילה (כבר {format_duration_he(elapsed)})')
    else:
        lines.append('תור: אין הורדה פעילה')
    if waiting:
        lines.append(f'ממתינות: {waiting}')
    return lines


def format_status_message(
    *,
    host_uptime,
    service_uptime,
    git_info: dict,
    version: str,
    queue_snapshot: dict,
    maintenance: bool = False,
    local_api: bool = False,
    max_file_size: int = MAX_FILE_SIZE,
    ytdlp_version: str | None = None,
    docker_status: dict | None = None,
) -> str:
    git_hash = git_info.get('hash')
    subject = (git_info.get('subject') or '').strip()

    lines = [
        '📊 סטטוס',
        '',
        f'שרת: {format_duration_he(host_uptime)}',
        f'סרוויס: {format_duration_he(service_uptime)}',
    ]
    docker_line = format_docker_line(docker_status)
    if docker_line:
        lines.append(docker_line)
    lines.append('')
    if git_hash:
        lines.append(f'קוד: {version} · {git_hash}')
        if subject:
            lines.append(subject)
        if git_info.get('dirty'):
            lines.append('עץ עבודה לא נקי (שינויים אחרי הקומיט)')
    else:
        lines.append(f'קוד: {version}')
        lines.append('קומיט: לא זמין')

    lines.append('')
    lines.extend(format_queue_lines(queue_snapshot))
    lines.append('')
    lines.append(format_file_limit_line(max_file_size, local_api))
    if ytdlp_version:
        lines.append(f'yt-dlp: {ytdlp_version}')
    lines.append('תחזוקה: כן ⚠️' if maintenance else 'תחזוקה: לא')
    return '\n'.join(lines)


def build_status_text(context) -> str:
    queue = context.bot_data.get('download_queue') if context else None
    snapshot = queue.snapshot() if queue else {
        'running': False,
        'running_elapsed': None,
        'waiting': 0,
        'total': 0,
    }
    return format_status_message(
        host_uptime=get_host_uptime_seconds(),
        service_uptime=get_service_uptime_seconds(),
        git_info=get_git_info(),
        version=VERSION,
        queue_snapshot=snapshot,
        maintenance=is_maintenance_mode(),
        local_api=LOCAL_API_AVAILABLE,
        max_file_size=MAX_FILE_SIZE,
        ytdlp_version=get_installed_ytdlp_version(),
        docker_status=get_docker_api_status(),
    )
