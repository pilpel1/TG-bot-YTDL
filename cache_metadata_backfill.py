"""השלמת metadata (תיאור/מעלה) לרשומות cache שנשמרו לפני שהתיאור נשמר בכלל.

רשומות ישנות מכילות רק file_id + כותרת, ולכן שליחה מהמטמון הציגה כותרת
בלבד במקום ה-caption המלא. כאן משלימים אותן בבת אחת, בלי להוריד אף קובץ -
רק extract_info של yt-dlp.

הרצה ידנית:
    python cache_metadata_backfill.py            # כל הרשומות החסרות
    python cache_metadata_backfill.py --limit 20 # רק 20 ראשונות
    python cache_metadata_backfill.py --dry-run  # רק לדווח, בלי לכתוב

בעליית הבוט זה רץ פעם אחת ברקע (ראו bot.post_init) כדי לא לעכב את ה-polling.
"""
from __future__ import annotations

import argparse
import asyncio
import time

import yt_dlp

from download_cache import (
    get_entries_missing_metadata,
    normalize_media_url,
    update_entry_metadata,
)
from logger_setup import logger

# הפסקה קצרה בין סרטונים כדי לא להיראות כמו סריקה אוטומטית מול יוטיוב
DEFAULT_PAUSE_SECONDS = 1.0


def fetch_video_metadata(url: str) -> dict:
    """שולף כותרת/תיאור/מעלה בלי להוריד את הקובץ."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False) or {}

    return {
        'title': info.get('title'),
        'description': info.get('description') or '',
        'uploader': info.get('uploader') or '',
    }


def backfill_missing_metadata(limit: int = None, pause_seconds: float = DEFAULT_PAUSE_SECONDS,
                              dry_run: bool = False) -> dict:
    """משלים metadata לכל רשומות הווידאו שחסר בהן תיאור.

    אותו סרטון יכול להופיע בכמה רשומות (איכות שונה = מפתח שונה), לכן
    מקבצים לפי URL מנורמל ושולפים פעם אחת לכל סרטון.
    """
    entries = get_entries_missing_metadata(download_mode='video', limit=limit)
    if not entries:
        logger.info("Cache metadata backfill: nothing to do")
        return {'videos': 0, 'updated': 0, 'failed': 0}

    entries_by_video = {}
    for entry in entries:
        entries_by_video.setdefault(normalize_media_url(entry['url']), []).append(entry)

    logger.info(
        f"Cache metadata backfill: {len(entries)} entries across "
        f"{len(entries_by_video)} videos (dry_run={dry_run})"
    )

    updated = 0
    failed = 0

    for index, video_entries in enumerate(entries_by_video.values()):
        url = video_entries[0]['url']
        try:
            metadata = fetch_video_metadata(url)
        except Exception as error:
            # סרטון שנמחק/נחסם יישאר NULL וינסה שוב בהרצה הבאה - עדיף
            # מלשמור תיאור ריק שיקבע לנצח שאין תיאור.
            failed += len(video_entries)
            logger.warning(f"Cache metadata backfill failed for {url}: {error}")
            continue

        for entry in video_entries:
            if dry_run:
                logger.info(f"[dry-run] would update {entry['cache_key']}")
            else:
                update_entry_metadata(
                    entry['cache_key'],
                    title=metadata['title'],
                    description=metadata['description'],
                    uploader=metadata['uploader'],
                )
            updated += 1

        if pause_seconds and index < len(entries_by_video) - 1:
            time.sleep(pause_seconds)

    logger.info(f"Cache metadata backfill done: updated={updated} failed={failed}")
    return {'videos': len(entries_by_video), 'updated': updated, 'failed': failed}


async def run_backfill_in_background(pause_seconds: float = DEFAULT_PAUSE_SECONDS):
    """מריץ את המיגרציה ב-thread נפרד כדי לא לחסום את ה-event loop."""
    try:
        return await asyncio.to_thread(backfill_missing_metadata, None, pause_seconds, False)
    except Exception as error:
        logger.error(f"Cache metadata backfill crashed: {error}")
        return None


def main():
    parser = argparse.ArgumentParser(description='השלמת תיאורים חסרים ב-cache ההורדות')
    parser.add_argument('--limit', type=int, default=None, help='מספר רשומות מקסימלי')
    parser.add_argument('--pause', type=float, default=DEFAULT_PAUSE_SECONDS,
                        help='שניות המתנה בין סרטונים')
    parser.add_argument('--dry-run', action='store_true', help='דיווח בלבד, בלי לעדכן')
    args = parser.parse_args()

    stats = backfill_missing_metadata(
        limit=args.limit,
        pause_seconds=args.pause,
        dry_run=args.dry_run,
    )
    print(f"videos={stats['videos']} updated={stats['updated']} failed={stats['failed']}")


if __name__ == '__main__':
    main()
