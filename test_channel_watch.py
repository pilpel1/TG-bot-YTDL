from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import channel_watch
from channel_watch import (
    find_new_entries,
    format_new_video_html,
    html_link,
    initialize_baselines,
    is_youtube_url,
    is_youtube_video_url,
    most_recent_watch_slot,
    next_watch_slot,
    normalize_youtube_channel_url,
    seconds_until_next_watch,
    source_tab_url,
    summarize_description_fallback,
    check_subscription_for_new_videos,
)
from user_settings import _normalize_sub


def test_normalize_youtube_channel_url():
    assert normalize_youtube_channel_url('https://www.youtube.com/@foo/videos') == (
        'https://www.youtube.com/@foo'
    )
    assert normalize_youtube_channel_url('https://youtube.com/@foo/shorts') == (
        'https://www.youtube.com/@foo'
    )
    assert normalize_youtube_channel_url('https://www.youtube.com/channel/UCabc123') == (
        'https://www.youtube.com/channel/UCabc123'
    )
    assert normalize_youtube_channel_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ') is None
    assert normalize_youtube_channel_url('https://youtu.be/dQw4w9WgXcQ') is None
    assert normalize_youtube_channel_url('https://tiktok.com/@foo') is None


def test_is_youtube_video_url():
    assert is_youtube_video_url('https://www.youtube.com/watch?v=abc')
    assert is_youtube_video_url('https://youtu.be/abc')
    assert is_youtube_video_url('https://www.youtube.com/shorts/abc')
    assert not is_youtube_video_url('https://www.youtube.com/@foo')
    assert is_youtube_url('https://www.youtube.com/@foo')


def test_source_tab_url():
    assert source_tab_url('https://www.youtube.com/@foo', 'shorts') == (
        'https://www.youtube.com/@foo/shorts'
    )


def test_find_new_entries_oldest_to_newest_via_reverse():
    entries = [
        {'video_id': 'new2', 'title': 'B'},
        {'video_id': 'new1', 'title': 'A'},
        {'video_id': 'old', 'title': 'Z'},
    ]
    found = find_new_entries(entries, 'old')
    assert [item['video_id'] for item in found] == ['new2', 'new1']
    assert find_new_entries(entries, 'new2') == []
    assert find_new_entries(entries, None) == []
    assert find_new_entries([], 'old') == []


def test_initialize_baselines_does_not_mark_existing_as_new():
    sub = _normalize_sub({
        'channel_url': 'https://www.youtube.com/@foo',
        'sources': ['videos', 'shorts'],
    })
    source_entries = {
        'videos': [{'video_id': 'v1', 'title': 'Latest video'}],
        'shorts': [{'video_id': 's1', 'title': 'Latest short'}],
    }
    initialize_baselines(sub, source_entries)
    assert sub['sources_state']['videos']['last_seen_video_id'] == 'v1'
    assert sub['sources_state']['shorts']['last_seen_video_id'] == 's1'


def test_check_subscription_finds_all_new_and_skips_notified():
    sub = _normalize_sub({
        'channel_url': 'https://www.youtube.com/@foo',
        'sources': ['videos'],
        'notified_video_ids': ['skipme'],
        'sources_state': {
            'videos': {'last_seen_video_id': 'old', 'last_seen_title': 'old'},
        },
    })
    entries = [
        {'video_id': 'new2', 'title': 'B', 'url': 'https://youtu.be/new2', 'source': 'videos'},
        {'video_id': 'skipme', 'title': 'S', 'url': 'https://youtu.be/skipme', 'source': 'videos'},
        {'video_id': 'old', 'title': 'O', 'url': 'https://youtu.be/old', 'source': 'videos'},
    ]
    with patch('channel_watch.fetch_source_entries', return_value=entries):
        updated, new_entries = check_subscription_for_new_videos(sub)

    # skipme כבר ב-notified — רק new2 נשלח, מהישן לחדש
    assert [item['video_id'] for item in new_entries] == ['new2']
    assert updated['sources_state']['videos']['last_seen_video_id'] == 'new2'
    assert 'new2' in updated['notified_video_ids']


def test_check_subscription_uninitialized_source_sets_baseline_only():
    sub = _normalize_sub({
        'channel_url': 'https://www.youtube.com/@foo',
        'sources': ['shorts'],
    })
    entries = [
        {'video_id': 's1', 'title': 'Short', 'url': 'https://youtu.be/s1', 'source': 'shorts'},
    ]
    with patch('channel_watch.fetch_source_entries', return_value=entries):
        updated, new_entries = check_subscription_for_new_videos(sub)
    assert new_entries == []
    assert updated['sources_state']['shorts']['last_seen_video_id'] == 's1'


def test_format_new_video_html_always_has_min_text_and_links():
    text = format_new_video_html(
        'ערוץ <x>',
        'https://www.youtube.com/@foo',
        'שיר & שם',
        'https://www.youtube.com/watch?v=abc',
    )
    assert 'העלה סרטון חדש' in text
    assert html_link('https://www.youtube.com/@foo', 'ערוץ <x>') in text
    assert '&amp;' in text
    assert '<a href=' in text
    assert 'תיאור' not in text


def test_format_new_video_html_appends_cleaned_description():
    text = format_new_video_html(
        'Foo',
        'https://www.youtube.com/@foo',
        'Title',
        'https://youtu.be/abc',
        'שורה ראשונה',
    )
    assert 'שורה ראשונה' in text


def test_summarize_description_fallback_strips_links():
    raw = "שיר חדש\nhttps://example.com/x\nעוד משפט"
    assert 'https://' not in summarize_description_fallback(raw)
    assert 'שיר חדש' in summarize_description_fallback(raw)
    assert summarize_description_fallback('') == ''


def test_seconds_until_next_watch_first_boot_waits():
    now = datetime(2026, 9, 6, 10, 0, 0, tzinfo=timezone.utc)
    with patch.object(channel_watch, 'CHANNEL_WATCH_HOURS', [8, 20]), \
         patch('channel_watch.get_watch_timezone', return_value=timezone.utc):
        delay = seconds_until_next_watch(now, last_run_at=None)
    assert delay == pytest.approx(10 * 3600)


def test_seconds_until_next_watch_missed_window_runs_now():
    now = datetime(2026, 9, 6, 10, 0, 0, tzinfo=timezone.utc)
    last_run = datetime(2026, 9, 5, 20, 0, 0, tzinfo=timezone.utc).isoformat()
    with patch.object(channel_watch, 'CHANNEL_WATCH_HOURS', [8, 20]), \
         patch('channel_watch.get_watch_timezone', return_value=timezone.utc):
        delay = seconds_until_next_watch(now, last_run_at=last_run)
    assert delay == 0.0


def test_seconds_until_next_watch_after_successful_morning_waits_for_evening():
    now = datetime(2026, 9, 6, 10, 0, 0, tzinfo=timezone.utc)
    last_run = datetime(2026, 9, 6, 8, 1, 0, tzinfo=timezone.utc).isoformat()
    with patch.object(channel_watch, 'CHANNEL_WATCH_HOURS', [8, 20]), \
         patch('channel_watch.get_watch_timezone', return_value=timezone.utc):
        delay = seconds_until_next_watch(now, last_run_at=last_run)
    assert 9.9 * 3600 <= delay <= 10.1 * 3600


def test_watch_slots():
    now = datetime(2026, 9, 6, 10, 0, 0, tzinfo=timezone.utc)
    with patch.object(channel_watch, 'CHANNEL_WATCH_HOURS', [8, 20]), \
         patch('channel_watch.get_watch_timezone', return_value=timezone.utc):
        recent = most_recent_watch_slot(now)
        upcoming = next_watch_slot(now)
    assert recent.hour == 8
    assert upcoming.hour == 20
    assert upcoming.date() == now.date()


def test_next_watch_slot_after_last_hour_goes_tomorrow():
    now = datetime(2026, 9, 6, 21, 0, 0, tzinfo=timezone.utc)
    with patch.object(channel_watch, 'CHANNEL_WATCH_HOURS', [8, 20]), \
         patch('channel_watch.get_watch_timezone', return_value=timezone.utc):
        upcoming = next_watch_slot(now)
    assert upcoming.hour == 8
    assert upcoming.date() == (now + timedelta(days=1)).date()
