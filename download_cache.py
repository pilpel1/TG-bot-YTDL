"""Cache של הורדות לפי file_id של טלגרם - כדי לא להוריד מיוטיוב פעמיים
את אותו סרטון/פורמט/איכות.

אחרי שליחת audio/video מקבלים בהודעה שחזרה file_id - מזהה קבוע שטלגרם
מכיר, שאפשר לשלוח בו-שוב בלי להעלות שום קובץ (send_audio(audio=file_id)).
שומרים אותו כאן, לפי מפתח (url מנורמל, download_mode, quality_name).

SQLite (לא JSON כמו user_settings) כי זה lookup לפי מפתח, לא מסמך שלם
שנטען ונשמר כל פעם - וגם צפוי לגדול הרבה יותר (כל הורדה, לא רק הגדרות).
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from config import DATA_DIR
from logger_setup import logger

DB_PATH = DATA_DIR / 'download_cache.db'

_lock = threading.Lock()
_local = threading.local()

YOUTUBE_HOSTS = {
    'youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be',
}


def _get_connection() -> sqlite3.Connection:
    """חיבור אחד לכל thread (sqlite3 לא אוהב לשתף חיבור בין threads)."""
    conn = getattr(_local, 'conn', None)
    if conn is not None:
        return conn

    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cached_downloads (
            cache_key TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            download_mode TEXT NOT NULL,
            quality_name TEXT NOT NULL,
            file_id TEXT NOT NULL,
            title TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    _local.conn = conn
    return conn


def normalize_media_url(url: str) -> str:
    """מנרמל URL להשוואת cache.

    ליוטיוב: מחלץ רק את מזהה הסרטון (מתעלם מ-list=, si=, t= וכו') - כך
    שאותו סרטון עם פרמטרים שונים (או בתוך פלייליסט/מיקס) עדיין יפגע ב-cache.
    לשאר הפלטפורמות: משאיר scheme+host+path בלבד (בלי query/fragment) -
    לא מושלם (למשל קישור מקוצר מול קישור שנפתר לא יתאימו), אבל מספיק
    לרוב המקרים בלי לגרור כאן את כל לוגיקת ה-normalize הספציפית-לפלטפורמה
    שגרה ב-download_manager.
    """
    url = (url or '').strip()
    try:
        parsed = urlparse(url)
    except Exception:
        return url.lower()

    host = (parsed.hostname or '').lower()
    if host.startswith('www.'):
        host = host[4:]

    if host in YOUTUBE_HOSTS:
        video_id = None
        if host == 'youtu.be':
            video_id = parsed.path.strip('/').split('/')[0] or None
        else:
            path = parsed.path or ''
            qs = parse_qs(parsed.query)
            if qs.get('v'):
                video_id = qs['v'][0]
            elif '/shorts/' in path:
                video_id = path.split('/shorts/')[-1].split('/')[0]
            elif '/embed/' in path:
                video_id = path.split('/embed/')[-1].split('/')[0]
        if video_id:
            return f'youtube:{video_id}'

    if not host:
        # לא URL אמיתי (או ריק) - אין host/scheme להתבסס עליהם, פשוט משווים
        # את המחרוזת כמו שהיא במקום לבנות '://...' חסר משמעות.
        return url.strip().lower()

    path = (parsed.path or '').rstrip('/')
    return f'{parsed.scheme}://{host}{path}'.lower()


def build_cache_key(url: str, download_mode: str, quality_name: str) -> str:
    normalized = normalize_media_url(url)
    return f'{normalized}|{download_mode}|{quality_name or ""}'


def get_cached_file(url: str, download_mode: str, quality_name: str) -> dict | None:
    """מחזיר {'file_id', 'title'} אם יש cache hit, אחרת None."""
    key = build_cache_key(url, download_mode, quality_name)
    with _lock:
        conn = _get_connection()
        row = conn.execute(
            'SELECT file_id, title FROM cached_downloads WHERE cache_key = ?',
            (key,),
        ).fetchone()
    if not row:
        return None
    return {'file_id': row['file_id'], 'title': row['title']}


def save_cached_file(url: str, download_mode: str, quality_name: str, file_id: str, title: str = None):
    if not file_id:
        return
    key = build_cache_key(url, download_mode, quality_name)
    with _lock:
        conn = _get_connection()
        conn.execute(
            """
            INSERT INTO cached_downloads (cache_key, url, download_mode, quality_name, file_id, title, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                file_id = excluded.file_id,
                title = excluded.title,
                created_at = excluded.created_at
            """,
            (key, url, download_mode, quality_name, file_id, title, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    logger.info(f"Cached file_id for key={key}")


def delete_cached_file(url: str, download_mode: str, quality_name: str):
    key = build_cache_key(url, download_mode, quality_name)
    with _lock:
        conn = _get_connection()
        conn.execute('DELETE FROM cached_downloads WHERE cache_key = ?', (key,))
        conn.commit()
    logger.info(f"Removed stale cache entry key={key}")
