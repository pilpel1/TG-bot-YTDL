import pytest

import download_cache
from download_cache import (
    normalize_media_url,
    build_cache_key,
    get_cached_file,
    save_cached_file,
    delete_cached_file,
)


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    """DB זמני לכל טסט + חיבור נקי (בלי זה thread-local יחזיק חיבור לקובץ
    הקודם/ל-DB האמיתי)."""
    monkeypatch.setattr(download_cache, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(download_cache, 'DB_PATH', tmp_path / 'download_cache.db')
    download_cache._local.conn = None
    yield
    conn = getattr(download_cache._local, 'conn', None)
    if conn is not None:
        conn.close()
    download_cache._local.conn = None


AUDIO_QUALITY = 'audio-only'
VIDEO_HIGH = 'high'
VIDEO_LOW = 'low'
VIDEO_REGULAR = 'regular'


# --- normalize_media_url ---

def test_normalize_youtube_watch_url_extracts_video_id():
    assert normalize_media_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ') == 'youtube:dQw4w9WgXcQ'


def test_normalize_youtube_ignores_playlist_param():
    """אותו סרטון עם list= (מתוך פלייליסט) חייב לפגוע באותו מפתח כמו
    בלי list= - אחרת cache לא היה עוזר לפלייליסטים בכלל."""
    plain = normalize_media_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
    with_list = normalize_media_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLxxx&index=3')
    assert plain == with_list


def test_normalize_youtu_be_short_link():
    assert normalize_media_url('https://youtu.be/dQw4w9WgXcQ?si=abc123') == 'youtube:dQw4w9WgXcQ'


def test_normalize_youtube_shorts():
    assert normalize_media_url('https://www.youtube.com/shorts/abcDEF123') == 'youtube:abcDEF123'


def test_normalize_non_youtube_strips_query_and_trailing_slash():
    a = normalize_media_url('https://www.tiktok.com/@user/video/123456?is_copy_url=1')
    b = normalize_media_url('https://www.tiktok.com/@user/video/123456/')
    assert a == b == 'https://tiktok.com/@user/video/123456'


def test_normalize_handles_garbage_without_raising():
    assert normalize_media_url('not a url at all') == 'not a url at all'


def test_normalize_empty_string():
    assert normalize_media_url('') == ''


# --- build_cache_key ---

def test_cache_key_differs_by_mode_and_quality():
    url = 'https://www.youtube.com/watch?v=abc'
    key_audio = build_cache_key(url, 'audio', AUDIO_QUALITY)
    key_video_high = build_cache_key(url, 'video', VIDEO_HIGH)
    key_video_low = build_cache_key(url, 'video', VIDEO_LOW)
    assert len({key_audio, key_video_high, key_video_low}) == 3


# --- get/save/delete round trip ---

def test_cache_miss_returns_none():
    assert get_cached_file('https://www.youtube.com/watch?v=missing', 'audio', AUDIO_QUALITY) is None


def test_save_then_get_returns_file_id_and_title():
    url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    save_cached_file(url, 'audio', AUDIO_QUALITY, 'FILE_ID_123', title='Never Gonna Give You Up')

    cached = get_cached_file(url, 'audio', AUDIO_QUALITY)
    assert cached == {'file_id': 'FILE_ID_123', 'title': 'Never Gonna Give You Up'}


def test_save_is_idempotent_upsert_on_same_key():
    url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    save_cached_file(url, 'video', VIDEO_REGULAR, 'OLD_FILE_ID', title='Old title')
    save_cached_file(url, 'video', VIDEO_REGULAR, 'NEW_FILE_ID', title='New title')

    cached = get_cached_file(url, 'video', VIDEO_REGULAR)
    assert cached == {'file_id': 'NEW_FILE_ID', 'title': 'New title'}

    # ולא נשארו כפולות בטבלה
    conn = download_cache._get_connection()
    count = conn.execute('SELECT COUNT(*) FROM cached_downloads').fetchone()[0]
    assert count == 1


def test_delete_removes_entry():
    url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    save_cached_file(url, 'audio', AUDIO_QUALITY, 'FILE_ID_123')
    assert get_cached_file(url, 'audio', AUDIO_QUALITY) is not None

    delete_cached_file(url, 'audio', AUDIO_QUALITY)
    assert get_cached_file(url, 'audio', AUDIO_QUALITY) is None


def test_delete_missing_entry_does_not_raise():
    delete_cached_file('https://www.youtube.com/watch?v=nope', 'audio', AUDIO_QUALITY)


def test_save_without_file_id_is_noop():
    url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    save_cached_file(url, 'audio', AUDIO_QUALITY, '')
    assert get_cached_file(url, 'audio', AUDIO_QUALITY) is None


def test_different_urls_do_not_collide():
    save_cached_file('https://www.youtube.com/watch?v=aaa', 'audio', AUDIO_QUALITY, 'FILE_A')
    save_cached_file('https://www.youtube.com/watch?v=bbb', 'audio', AUDIO_QUALITY, 'FILE_B')

    assert get_cached_file('https://www.youtube.com/watch?v=aaa', 'audio', AUDIO_QUALITY)['file_id'] == 'FILE_A'
    assert get_cached_file('https://www.youtube.com/watch?v=bbb', 'audio', AUDIO_QUALITY)['file_id'] == 'FILE_B'


def test_db_file_created_on_disk():
    save_cached_file('https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'audio', AUDIO_QUALITY, 'FILE_ID')
    assert download_cache.DB_PATH.exists()
