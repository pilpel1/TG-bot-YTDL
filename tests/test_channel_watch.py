from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

import pytest

import channel_watch
import user_settings
from channel_watch import (
    CHANNEL_WATCH_RETRY_SECONDS,
    ChannelWatchManager,
    _video_id_from_item,
    deliver_new_video,
    fetch_source_entries,
    find_new_entries,
    format_new_video_html,
    format_watch_schedule_he,
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
from user_settings import (
    _normalize_sub,
    add_channel_sub,
    get_channel_watch_last_run,
    list_channel_subs,
)


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
    assert source_tab_url('https://www.youtube.com/@foo', 'videos') == (
        'https://www.youtube.com/@foo/videos?view=0&sort=dd'
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
    assert sub['sources_state']['videos']['seen_video_ids'] == ['v1']
    assert sub['sources_state']['shorts']['seen_video_ids'] == ['s1']
    assert set(sub['notified_video_ids']) == {'v1', 's1'}


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

    # skipme כבר ב-notified — רק new2 נשלח, מהישן לחדש.
    # new2 נכנס ל-notified רק אחרי שליחה מוצלחת, לא כאן.
    assert [item['video_id'] for item in new_entries] == ['new2']
    assert updated['sources_state']['videos']['last_seen_video_id'] == 'new2'
    assert 'new2' not in updated['notified_video_ids']
    assert 'old' in updated['notified_video_ids']
    assert 'skipme' in updated['notified_video_ids']
    assert updated['sources_state']['videos']['seen_video_ids'] == [
        'new2', 'skipme', 'old',
    ]


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
    assert updated['sources_state']['shorts']['seen_video_ids'] == ['s1']
    assert 's1' in updated['notified_video_ids']


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


def test_format_watch_schedule_he():
    assert format_watch_schedule_he([]) == 'הבדיקה האוטומטית כבויה כרגע'
    assert format_watch_schedule_he([8]) == 'פעם ביום, ב-08:00'
    assert format_watch_schedule_he([8, 20]) == 'פעמיים ביום, ב-08:00 ו-20:00'
    assert format_watch_schedule_he([8, 12, 21]) == '3 פעמים ביום, ב-08:00, 12:00 ו-21:00'


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


def test_check_subscription_finds_new_below_sticky_first_item():
    sub = _normalize_sub({
        'channel_url': 'https://www.youtube.com/@foo',
        'sources': ['videos'],
        'notified_video_ids': ['sticky', 'old'],
        'sources_state': {
            'videos': {
                'last_seen_video_id': 'sticky',
                'last_seen_title': 'live',
                'seen_video_ids': ['sticky', 'old'],
            },
        },
    })
    entries = [
        {'video_id': 'sticky', 'title': 'Live', 'url': 'https://youtu.be/sticky', 'source': 'videos'},
        {'video_id': 'new1', 'title': 'New', 'url': 'https://youtu.be/new1', 'source': 'videos'},
        {'video_id': 'old', 'title': 'Old', 'url': 'https://youtu.be/old', 'source': 'videos'},
    ]
    with patch('channel_watch.fetch_source_entries', return_value=entries):
        updated, new_entries = check_subscription_for_new_videos(sub)
    assert [item['video_id'] for item in new_entries] == ['new1']
    assert 'new1' not in updated['notified_video_ids']
    assert updated['sources_state']['videos']['seen_video_ids'] == [
        'sticky', 'new1', 'old',
    ]


def test_check_subscription_missing_last_seen_does_not_dump_window():
    sub = _normalize_sub({
        'channel_url': 'https://www.youtube.com/@foo',
        'sources': ['videos'],
        'notified_video_ids': [],
        'sources_state': {
            'videos': {'last_seen_video_id': 'gone', 'last_seen_title': 'gone'},
        },
    })
    entries = [
        {'video_id': 'a', 'title': 'A', 'url': 'https://youtu.be/a', 'source': 'videos'},
        {'video_id': 'b', 'title': 'B', 'url': 'https://youtu.be/b', 'source': 'videos'},
    ]
    with patch('channel_watch.fetch_source_entries', return_value=entries):
        updated, new_entries = check_subscription_for_new_videos(sub)
    assert new_entries == []
    assert set(updated['notified_video_ids']) == {'a', 'b'}
    assert updated['sources_state']['videos']['seen_video_ids'] == ['a', 'b']


def test_video_id_from_item_skips_playlist_ids():
    assert _video_id_from_item({'id': 'abcdefghijk'}) == 'abcdefghijk'
    assert _video_id_from_item({'id': 'UULFabcdefghijabcdefghij'}) is None
    assert _video_id_from_item({
        'id': 'playlist',
        'url': 'https://www.youtube.com/watch?v=abcdefghijk',
    }) == 'abcdefghijk'


def test_fetch_source_entries_skips_playlist_ids_and_flattens():
    data = {
        'entries': [
            {'id': 'UULFabcdefghijabcdefghij', 'title': 'Uploads'},
            {
                'id': 'abcdefghijk',
                'title': 'Vid',
                'url': 'https://www.youtube.com/watch?v=abcdefghijk',
            },
            {
                'entries': [{
                    'id': 'bcdefghijkl',
                    'title': 'Nested',
                    'url': 'https://youtu.be/bcdefghijkl',
                }],
            },
        ]
    }

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return data

    with patch('channel_watch.yt_dlp.YoutubeDL', FakeYDL):
        entries = fetch_source_entries('https://www.youtube.com/@foo', 'videos')
    assert [item['video_id'] for item in entries] == ['abcdefghijk', 'bcdefghijkl']


def _subs_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(user_settings, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(user_settings, 'CHANNEL_SUBS_FILE', tmp_path / 'channel_subscriptions.json')


@pytest.mark.asyncio
async def test_run_check_marks_notified_only_after_successful_delivery(tmp_path, monkeypatch):
    _subs_tmp(tmp_path, monkeypatch)
    add_channel_sub(7, _normalize_sub({
        'channel_url': 'https://www.youtube.com/@foo',
        'channel_id': 'UCaaa',
        'channel_label': 'Foo',
        'sources': ['videos'],
        'notified_video_ids': ['old'],
        'sources_state': {
            'videos': {
                'last_seen_video_id': 'old',
                'last_seen_title': 'old',
                'seen_video_ids': ['old'],
            },
        },
    }))
    entries = [
        {'video_id': 'new1', 'title': 'N', 'url': 'https://youtu.be/new1', 'source': 'videos'},
        {'video_id': 'old', 'title': 'O', 'url': 'https://youtu.be/old', 'source': 'videos'},
    ]
    manager = ChannelWatchManager(MagicMock())
    with patch('channel_watch.fetch_source_entries', return_value=entries), \
         patch('channel_watch.is_maintenance_mode', return_value=False), \
         patch('channel_watch.deliver_new_video', AsyncMock(side_effect=RuntimeError('boom'))):
        assert await manager.run_check() is True
    stored = list_channel_subs(7)[0]
    assert 'new1' not in stored['notified_video_ids']
    assert 'old' in stored['notified_video_ids']

    with patch('channel_watch.fetch_source_entries', return_value=entries), \
         patch('channel_watch.is_maintenance_mode', return_value=False), \
         patch('channel_watch.deliver_new_video', AsyncMock()) as mock_deliver:
        assert await manager.run_check() is True
        assert mock_deliver.call_count == 1
        assert mock_deliver.call_args.args[3]['video_id'] == 'new1'
    stored = list_channel_subs(7)[0]
    assert 'new1' in stored['notified_video_ids']


@pytest.mark.asyncio
async def test_run_check_skips_maintenance_without_last_run(tmp_path, monkeypatch):
    _subs_tmp(tmp_path, monkeypatch)
    manager = ChannelWatchManager(MagicMock())
    with patch('channel_watch.is_maintenance_mode', return_value=True):
        assert await manager.run_check() is False
    assert get_channel_watch_last_run() is None


@pytest.mark.asyncio
async def test_scheduler_retries_without_marking_last_run():
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError()

    manager = ChannelWatchManager(MagicMock())
    with patch('channel_watch.seconds_until_next_watch', return_value=0), \
         patch.object(manager, 'run_check', AsyncMock(return_value=False)), \
         patch('channel_watch.asyncio.sleep', fake_sleep), \
         patch('channel_watch.set_channel_watch_last_run') as mock_set:
        with pytest.raises(asyncio.CancelledError):
            await manager._scheduler_loop()
    assert mock_set.call_count == 0
    assert sleeps == [CHANNEL_WATCH_RETRY_SECONDS, CHANNEL_WATCH_RETRY_SECONDS]


@pytest.mark.asyncio
async def test_deliver_new_video_deletes_status_only_after_last_mode():
    calls = []

    async def fake_download(context, status_message, url, mode, quality, quality_levels,
                             should_cancel=None, quiet_complete=False, delete_status=True,
                             **kwargs):
        calls.append({
            'mode': mode,
            'delete_status': delete_status,
            'quiet_complete': quiet_complete,
        })

    class FakeQueue:
        async def enqueue(self, chat_id, status_message, coro_factory, weight=1, cancel_token=None):
            await coro_factory()

    app = MagicMock()
    app.bot.send_message = AsyncMock(return_value=MagicMock())
    app.bot_data = {'download_queue': FakeQueue()}
    sub = {
        'delivery': ['audio', 'video'],
        'channel_label': 'Foo',
        'channel_url': 'https://www.youtube.com/@foo',
        'include_description': False,
    }
    with patch('channel_watch.download_with_quality', fake_download), \
         patch('channel_watch.is_maintenance_mode', return_value=False), \
         patch('channel_watch.remember_chat'):
        await deliver_new_video(
            app, 1, sub,
            {'video_id': 'abcdefghijk', 'url': 'https://youtu.be/abcdefghijk', 'title': 'T'},
        )

    assert [item['mode'] for item in calls] == ['audio', 'video']
    assert calls[0]['delete_status'] is False
    assert calls[1]['delete_status'] is True
    assert all(item['quiet_complete'] for item in calls)
