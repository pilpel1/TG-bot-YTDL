"""בדיקות למיגרציה שמשלימה תיאורים לרשומות cache ישנות."""
from unittest.mock import patch

import pytest

import cache_metadata_backfill
import download_cache
from cache_metadata_backfill import backfill_missing_metadata
from download_cache import get_cached_file, save_cached_file

VIDEO_TOKEN = 'h720'
URL = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'

METADATA = {
    'title': 'Fresh title',
    'description': 'התיאור המלא',
    'uploader': 'Some Channel',
}


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(download_cache, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(download_cache, 'DB_PATH', tmp_path / 'cache.db')
    download_cache._local.conn = None
    yield
    conn = getattr(download_cache._local, 'conn', None)
    if conn is not None:
        conn.close()
    download_cache._local.conn = None


def test_backfill_fills_description_for_legacy_entry():
    save_cached_file(URL, 'video', VIDEO_TOKEN, 'FILE_ID', title='Old title')

    with patch.object(cache_metadata_backfill, 'fetch_video_metadata', return_value=METADATA):
        stats = backfill_missing_metadata(pause_seconds=0)

    assert stats == {'videos': 1, 'updated': 1, 'failed': 0}
    cached = get_cached_file(URL, 'video', VIDEO_TOKEN)
    assert cached['description'] == 'התיאור המלא'
    assert cached['uploader'] == 'Some Channel'
    assert cached['title'] == 'Fresh title'
    # file_id לא נגענו בו - הקובץ בטלגרם נשאר אותו קובץ
    assert cached['file_id'] == 'FILE_ID'


def test_backfill_fetches_once_per_video_for_multiple_qualities():
    """אותו סרטון בכמה איכויות = כמה שורות, אבל שליפת metadata אחת."""
    save_cached_file(URL, 'video', 'h1080', 'FILE_1080')
    save_cached_file(URL, 'video', 'h720', 'FILE_720')
    save_cached_file(URL + '&list=PLxxx', 'video', 'h480', 'FILE_480')

    with patch.object(cache_metadata_backfill, 'fetch_video_metadata',
                      return_value=METADATA) as mock_fetch:
        stats = backfill_missing_metadata(pause_seconds=0)

    assert mock_fetch.call_count == 1
    assert stats['videos'] == 1
    assert stats['updated'] == 3


def test_backfill_skips_already_filled_entries():
    save_cached_file(URL, 'video', VIDEO_TOKEN, 'FILE_ID', title='t', description='', uploader='')

    with patch.object(cache_metadata_backfill, 'fetch_video_metadata') as mock_fetch:
        stats = backfill_missing_metadata(pause_seconds=0)

    mock_fetch.assert_not_called()
    assert stats == {'videos': 0, 'updated': 0, 'failed': 0}


def test_backfill_ignores_audio_entries():
    """שליחת אודיו לא משתמשת בתיאור, אז אין טעם לבזבז עליה קריאת רשת."""
    save_cached_file(URL, 'audio', 'audio', 'FILE_ID')

    with patch.object(cache_metadata_backfill, 'fetch_video_metadata') as mock_fetch:
        stats = backfill_missing_metadata(pause_seconds=0)

    mock_fetch.assert_not_called()
    assert stats['updated'] == 0


def test_failed_fetch_leaves_entry_for_next_run():
    """סרטון שנמחק/נחסם נשאר NULL - לא נשמר תיאור ריק שיקבע 'אין תיאור'."""
    save_cached_file(URL, 'video', VIDEO_TOKEN, 'FILE_ID', title='Old title')

    with patch.object(cache_metadata_backfill, 'fetch_video_metadata',
                      side_effect=Exception('video unavailable')):
        stats = backfill_missing_metadata(pause_seconds=0)

    assert stats['failed'] == 1
    assert stats['updated'] == 0
    assert get_cached_file(URL, 'video', VIDEO_TOKEN)['description'] is None


def test_dry_run_does_not_write():
    save_cached_file(URL, 'video', VIDEO_TOKEN, 'FILE_ID', title='Old title')

    with patch.object(cache_metadata_backfill, 'fetch_video_metadata', return_value=METADATA):
        stats = backfill_missing_metadata(pause_seconds=0, dry_run=True)

    assert stats['updated'] == 1
    assert get_cached_file(URL, 'video', VIDEO_TOKEN)['description'] is None


def test_limit_caps_number_of_entries():
    save_cached_file('https://www.youtube.com/watch?v=aaa', 'video', VIDEO_TOKEN, 'FILE_A')
    save_cached_file('https://www.youtube.com/watch?v=bbb', 'video', VIDEO_TOKEN, 'FILE_B')

    with patch.object(cache_metadata_backfill, 'fetch_video_metadata',
                      return_value=METADATA) as mock_fetch:
        stats = backfill_missing_metadata(limit=1, pause_seconds=0)

    assert mock_fetch.call_count == 1
    assert stats['updated'] == 1
