import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, Message, Chat, User
from telegram.error import Forbidden
from telegram.ext import ContextTypes

import config
from broadcast import (
    is_admin,
    list_broadcast_targets,
    copy_broadcast_message,
    run_broadcast,
)
from bot_handlers import (
    ask_format,
    broadcast_command,
    button_click,
    mode,
    users_command,
)


@pytest.fixture
def admin_id():
    return 42


@pytest.fixture
def mock_update(admin_id):
    update = MagicMock(spec=Update)
    message = MagicMock(spec=Message)
    chat = MagicMock(spec=Chat)
    user = MagicMock(spec=User)
    chat.id = admin_id
    user.id = admin_id
    message.chat = chat
    message.chat_id = admin_id
    message.message_id = 10
    message.from_user = user
    message.reply_to_message = None
    message.reply_text = AsyncMock()
    update.message = message
    update.effective_chat = chat
    update.effective_user = user
    return update


@pytest.fixture
def mock_context():
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {}
    context.bot_data = {}
    context.bot = MagicMock()
    context.bot.copy_message = AsyncMock()
    context.bot.set_my_commands = AsyncMock()
    return context


def test_is_admin_reads_config(monkeypatch, admin_id):
    monkeypatch.setattr(config, 'ADMIN_USER_IDS', frozenset({admin_id}))
    assert is_admin(admin_id) is True
    assert is_admin(str(admin_id)) is True
    assert is_admin(99) is False
    assert is_admin(None) is False


def test_list_broadcast_targets_includes_all(monkeypatch):
    monkeypatch.setattr(
        'broadcast.list_known_chat_ids',
        lambda: ['42', '100', '200'],
    )
    assert list_broadcast_targets() == [42, 100, 200]


@pytest.mark.asyncio
async def test_copy_broadcast_message_blocked():
    bot = MagicMock()
    bot.copy_message = AsyncMock(side_effect=Forbidden('blocked'))
    assert await copy_broadcast_message(bot, 1, 2, 3) == 'blocked'


@pytest.mark.asyncio
async def test_run_broadcast_counts_and_skips_sleep_after_last(monkeypatch):
    monkeypatch.setattr('broadcast.BROADCAST_DELAY_SECONDS', 0)
    bot = MagicMock()
    bot.copy_message = AsyncMock(side_effect=[None, Forbidden('no'), RuntimeError('x')])
    sent, blocked, failed = await run_broadcast(bot, 42, 10, [1, 2, 3])
    assert (sent, blocked, failed) == (1, 1, 1)
    assert bot.copy_message.await_count == 3


@pytest.mark.asyncio
async def test_broadcast_command_silent_for_non_admin(mock_update, mock_context, monkeypatch):
    monkeypatch.setattr(config, 'ADMIN_USER_IDS', frozenset({42}))
    mock_update.effective_user.id = 99
    await broadcast_command(mock_update, mock_context)
    mock_update.message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_mode_command_silent_for_non_admin(mock_update, mock_context, monkeypatch):
    monkeypatch.setattr(config, 'ADMIN_USER_IDS', frozenset({42}))
    mock_update.effective_user.id = 99
    await mode(mock_update, mock_context)
    mock_update.message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_mode_command_replies_for_admin(mock_update, mock_context, monkeypatch):
    monkeypatch.setattr(config, 'ADMIN_USER_IDS', frozenset({42}))
    await mode(mock_update, mock_context)
    mock_update.message.reply_text.assert_awaited()
    text = mock_update.message.reply_text.call_args[0][0]
    assert 'מצב הבוט הנוכחי' in text


@pytest.mark.asyncio
async def test_users_command_silent_for_non_admin(mock_update, mock_context, monkeypatch):
    monkeypatch.setattr(config, 'ADMIN_USER_IDS', frozenset({42}))
    mock_update.effective_user.id = 99
    await users_command(mock_update, mock_context)
    mock_update.message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_broadcast_command_waits_for_next_message(mock_update, mock_context, monkeypatch):
    monkeypatch.setattr(config, 'ADMIN_USER_IDS', frozenset({42}))
    await broadcast_command(mock_update, mock_context)
    assert mock_context.user_data['awaiting_broadcast'] is True
    mock_update.message.reply_text.assert_awaited()


@pytest.mark.asyncio
async def test_broadcast_command_reply_offers_confirm(mock_update, mock_context, monkeypatch, admin_id):
    monkeypatch.setattr(config, 'ADMIN_USER_IDS', frozenset({admin_id}))
    photo = MagicMock(spec=Message)
    photo.chat_id = admin_id
    photo.message_id = 77
    mock_update.message.reply_to_message = photo
    with patch('bot_handlers.list_broadcast_targets', return_value=[100, 200]), \
         patch('bot_handlers.backfill_known_user_profiles', new_callable=AsyncMock), \
         patch('bot_handlers.format_known_user_label', side_effect=lambda chat_id, record=None: str(chat_id)):
        await broadcast_command(mock_update, mock_context)
    assert mock_context.user_data['broadcast_message_id'] == 77
    text = mock_update.message.reply_text.call_args[0][0]
    assert '2 משתמשים' in text


@pytest.mark.asyncio
async def test_ask_format_intercepts_awaiting_broadcast(mock_update, mock_context, monkeypatch, admin_id):
    monkeypatch.setattr(config, 'ADMIN_USER_IDS', frozenset({admin_id}))
    mock_update.message.text = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    mock_context.user_data['awaiting_broadcast'] = True
    with patch('bot_handlers.ensure_command_menu_synced', new_callable=AsyncMock), \
         patch('bot_handlers.list_broadcast_targets', return_value=[100]), \
         patch('bot_handlers.backfill_known_user_profiles', new_callable=AsyncMock), \
         patch('bot_handlers.format_known_user_label', side_effect=lambda chat_id, record=None: str(chat_id)), \
         patch('bot_handlers.begin_youtube_download_flow') as start_dl:
        await ask_format(mock_update, mock_context)
    start_dl.assert_not_called()
    assert mock_context.user_data['broadcast_message_id'] == 10


@pytest.mark.asyncio
async def test_button_broadcast_cancel(mock_update, mock_context, monkeypatch, admin_id):
    monkeypatch.setattr(config, 'ADMIN_USER_IDS', frozenset({admin_id}))
    query = AsyncMock()
    query.data = 'bc_no'
    query.from_user = MagicMock()
    query.from_user.id = admin_id
    query.message = MagicMock()
    query.message.edit_text = AsyncMock()
    mock_update.callback_query = query
    mock_context.user_data['broadcast_message_id'] = 77
    await button_click(mock_update, mock_context)
    assert 'broadcast_message_id' not in mock_context.user_data
    query.message.edit_text.assert_awaited_with('השידור בוטל.')


@pytest.mark.asyncio
async def test_button_broadcast_ok_copies_to_targets(mock_update, mock_context, monkeypatch, admin_id):
    monkeypatch.setattr(config, 'ADMIN_USER_IDS', frozenset({admin_id}))
    query = AsyncMock()
    query.data = 'bc_ok'
    query.from_user = MagicMock()
    query.from_user.id = admin_id
    query.message = MagicMock()
    query.message.edit_text = AsyncMock()
    mock_update.callback_query = query
    mock_context.user_data['broadcast_from_chat_id'] = admin_id
    mock_context.user_data['broadcast_message_id'] = 77
    with patch('bot_handlers.list_broadcast_targets', return_value=[100, 200]), \
         patch('bot_handlers.run_broadcast', new_callable=AsyncMock, return_value=(2, 0, 0)) as run:
        await button_click(mock_update, mock_context)
    run.assert_awaited_once()
    assert run.call_args.args[3] == [100, 200]
    assert mock_context.bot_data.get('broadcast_running') is False
    last_text = query.message.edit_text.call_args_list[-1].args[0]
    assert 'נשלח: 2' in last_text
