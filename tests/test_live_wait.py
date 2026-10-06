"""המתנה ללייב: שמירה בדיסק, בדיקה חוזרת, הורדה או כישלון שקט."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import live_wait
from live_wait import (
    LiveWaitManager,
    add_live_wait,
    cancel_live_waits_for_chat,
    format_live_failure,
    list_live_waits,
    maybe_register_live_wait,
    needs_live_wait,
    seconds_until_next_live_action,
    youtube_wait_key,
)
from bot_handlers import button_click, stop_download
from utils import build_youtube_audio_option


NOW = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)
URL = 'https://www.youtube.com/watch?v=abcdefghijk'
LIVE_URL = 'https://www.youtube.com/live/abcdefghijk'
AUDIO = build_youtube_audio_option()


@pytest.fixture
def waits_file(tmp_path, monkeypatch):
    monkeypatch.setattr(live_wait, 'LIVE_WAITS_FILE', tmp_path / 'live_waits.json')
    monkeypatch.setattr(live_wait, 'remember_chat', lambda *args, **kwargs: None)


def _live(status='is_live', title='שידור', video_id='abcdefghijk'):
    return {
        'probed': True,
        'live_status': status,
        'is_live': status == 'is_live',
        'title': title,
        'video_id': video_id,
    }


@pytest.mark.parametrize('status,is_live,expected', [
    ('is_live', True, True),
    ('is_upcoming', False, True),
    ('post_live', False, True),
    ('was_live', False, False),
    ('not_live', False, False),
    (None, False, False),
    (None, True, True),
])
def test_needs_live_wait(status, is_live, expected):
    assert needs_live_wait({'live_status': status, 'is_live': is_live}) is expected


def test_needs_live_wait_missing_snapshot_is_false():
    assert needs_live_wait(None) is False


def test_watch_and_live_urls_share_a_key():
    assert youtube_wait_key(URL) == 'youtube:abcdefghijk'
    assert youtube_wait_key(LIVE_URL) == 'youtube:abcdefghijk'


def test_wait_survives_reread_and_same_video_resets_deadline(waits_file):
    first, replaced = add_live_wait(7, LIVE_URL, 'audio', AUDIO, _live(), now=NOW)
    assert replaced is False
    assert first['url'] == URL
    assert first['deadline_at'] == (NOW + timedelta(hours=48)).isoformat()

    later = NOW + timedelta(hours=5)
    video = build_youtube_audio_option()
    video['quality_name'] = 'אודיו אחר'
    second, replaced = add_live_wait(7, URL, 'audio', video, _live(title='אחר'), now=later)
    assert replaced is True
    stored = list_live_waits()
    assert len(stored) == 1
    assert stored[0]['id'] == second['id']
    assert stored[0]['title'] == 'אחר'
    assert stored[0]['deadline_at'] == (later + timedelta(hours=48)).isoformat()
    assert seconds_until_next_live_action(now=later) == pytest.approx(3600)


def test_other_chat_is_not_cancelled(waits_file):
    add_live_wait(7, URL, 'audio', AUDIO, _live(), now=NOW)
    add_live_wait(8, URL, 'audio', AUDIO, _live(), now=NOW)
    assert cancel_live_waits_for_chat(7) == 1
    assert cancel_live_waits_for_chat(7) == 0
    left = list_live_waits()
    assert len(left) == 1
    assert left[0]['chat_id'] == 8


def _manager():
    app = MagicMock()
    app.bot.send_message = AsyncMock()
    app.bot_data = {'download_queue': AsyncMock()}
    return LiveWaitManager(app), app


@pytest.mark.asyncio
async def test_due_live_stays_pending_until_next_hour(waits_file):
    created = NOW - timedelta(hours=1)
    add_live_wait(7, URL, 'audio', AUDIO, _live(), now=created)
    manager, app = _manager()
    with patch('live_wait.probe_youtube_live', return_value={
        'live_status': 'post_live', 'is_live': False, 'title': 'שידור', 'id': 'abcdefghijk',
    }):
        assert await manager.run_due(now=NOW) is True
    app.bot.send_message.assert_not_awaited()
    app.bot_data['download_queue'].enqueue.assert_not_awaited()
    stored = list_live_waits()
    assert len(stored) == 1
    assert stored[0]['last_live_status'] == 'post_live'
    assert stored[0]['next_check_at'] == (NOW + timedelta(hours=1)).isoformat()


@pytest.mark.asyncio
async def test_ready_recording_is_queued_and_removed(waits_file):
    add_live_wait(7, URL, 'audio', AUDIO, _live(), now=NOW - timedelta(hours=1))
    manager, app = _manager()
    app.bot.send_message.return_value = MagicMock()
    with patch('live_wait.probe_youtube_live', return_value={
        'live_status': 'was_live', 'is_live': False, 'title': 'ההופעה', 'id': 'abcdefghijk',
    }):
        assert await manager.run_due(now=NOW) is True
    app.bot.send_message.assert_awaited_once()
    assert app.bot.send_message.await_args.kwargs['text'] == 'ההקלטה עלתה. מוריד... ⏳'
    assert 'disable_notification' not in app.bot.send_message.await_args.kwargs
    app.bot_data['download_queue'].enqueue.assert_awaited_once()
    queued = app.bot_data['download_queue'].enqueue.await_args.kwargs
    assert queued['chat_id'] == 7
    assert list_live_waits() == []


@pytest.mark.asyncio
async def test_expired_live_sends_silent_failure_and_is_removed(waits_file):
    add_live_wait(7, URL, 'audio', AUDIO, _live(title='הופעה'), now=NOW - timedelta(hours=49))
    manager, app = _manager()
    with patch('live_wait.probe_youtube_live', return_value={
        'live_status': 'is_live', 'is_live': True, 'title': 'הופעה', 'id': 'abcdefghijk',
    }):
        assert await manager.run_due(now=NOW) is True
    app.bot_data['download_queue'].enqueue.assert_not_awaited()
    sent = app.bot.send_message.await_args.kwargs
    assert sent['disable_notification'] is True
    assert sent['text'] == format_live_failure({'title': 'הופעה'})
    assert '48' in sent['text']
    assert list_live_waits() == []


@pytest.mark.asyncio
async def test_probe_error_before_deadline_keeps_the_wait(waits_file):
    add_live_wait(7, URL, 'audio', AUDIO, _live(), now=NOW - timedelta(hours=1))
    manager, app = _manager()
    with patch('live_wait.probe_youtube_live', side_effect=RuntimeError('youtube down')):
        assert await manager.run_due(now=NOW) is True
    app.bot.send_message.assert_not_awaited()
    stored = list_live_waits()
    assert len(stored) == 1
    assert stored[0]['next_check_at'] == (NOW + timedelta(hours=1)).isoformat()


@pytest.mark.asyncio
async def test_probe_error_after_deadline_fails_silently(waits_file):
    add_live_wait(7, URL, 'audio', AUDIO, _live(), now=NOW - timedelta(hours=49))
    manager, app = _manager()
    with patch('live_wait.probe_youtube_live', side_effect=RuntimeError('youtube down')):
        await manager.run_due(now=NOW)
    assert app.bot.send_message.await_args.kwargs['disable_notification'] is True
    assert list_live_waits() == []


@pytest.mark.asyncio
async def test_maintenance_does_not_move_the_deadline(waits_file):
    add_live_wait(7, URL, 'audio', AUDIO, _live(), now=NOW - timedelta(hours=1))
    before = list_live_waits()[0]['next_check_at']
    manager, app = _manager()
    with patch('live_wait.is_maintenance_mode', return_value=True):
        assert await manager.run_due(now=NOW) is False
    app.bot.send_message.assert_not_awaited()
    assert list_live_waits()[0]['next_check_at'] == before


def _callback(data, url, chat_id=77):
    update = MagicMock()
    query = AsyncMock()
    query.data = data
    message = MagicMock()
    message.chat_id = chat_id
    message.chat = MagicMock()
    message.edit_text = AsyncMock()
    message.reply_text = AsyncMock()
    query.message = message
    update.callback_query = query
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    context = MagicMock()
    context.bot_data = {}
    context.user_data = {
        'current_url': url,
        'is_youtube': True,
    }
    return update, context, message


@pytest.mark.asyncio
async def test_audio_choice_on_live_saves_wait_instead_of_enqueue(waits_file):
    update, context, message = _callback('audio', LIVE_URL)
    with patch('bot_handlers.enqueue_download_job', new=AsyncMock()) as enqueue, \
         patch('live_wait.probe_youtube_live', return_value={
             'live_status': 'is_upcoming', 'is_live': False, 'title': 'הופעה', 'id': 'abcdefghijk',
         }) as probe:
        await button_click(update, context)
    enqueue.assert_not_awaited()
    probe.assert_called_once()
    text = message.edit_text.await_args.args[0]
    assert '48' in text
    assert 'הודעה שקטה' in text
    assert '/stop' in text
    stored = list_live_waits()
    assert len(stored) == 1
    assert stored[0]['chat_id'] == 77
    assert stored[0]['download_mode'] == 'audio'
    assert stored[0]['url'] == URL


@pytest.mark.asyncio
async def test_audio_choice_reuses_prefetch_snapshot_without_second_probe(waits_file):
    update, context, message = _callback('audio', URL)

    async def prefetch():
        return {
            'download_options': [],
            'live': _live(status='is_live', title='חי'),
        }

    context.user_data['youtube_prefetch_task'] = asyncio.create_task(prefetch())
    context.user_data['youtube_prefetch_url'] = URL
    with patch('bot_handlers.enqueue_download_job', new=AsyncMock()) as enqueue, \
         patch('live_wait.probe_youtube_live', side_effect=AssertionError('probe')) as probe:
        await button_click(update, context)
    enqueue.assert_not_awaited()
    probe.assert_not_called()
    assert 'השידור עוד חי' in message.edit_text.await_args.args[0]
    assert list_live_waits()[0]['url_key'] == 'youtube:abcdefghijk'


@pytest.mark.asyncio
async def test_stop_cancels_live_wait_without_an_active_download(waits_file):
    add_live_wait(77, URL, 'audio', AUDIO, _live(), now=NOW)
    update = MagicMock()
    update.effective_chat.id = 77
    update.message.reply_text = AsyncMock()
    queue = MagicMock()
    queue.cancel_all_for_chat.return_value = 0
    context = MagicMock()
    context.bot_data = {'download_queue': queue}
    await stop_download(update, context)
    assert list_live_waits() == []
    assert 'המתנה ללייב' in update.message.reply_text.await_args.args[0]
    queue.cancel_all_for_chat.assert_called_once_with(77)
