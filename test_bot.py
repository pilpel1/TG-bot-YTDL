import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, Message, Chat, User, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot_handlers import (
    is_valid_url, is_preferred_platform, is_thank_you_message,
    start, ask_format, button_click, handle_thank_you
)
from config import YOUTUBE_QUALITY_LEVELS

# Fixtures
@pytest.fixture
def mock_update():
    update = MagicMock(spec=Update)
    message = MagicMock(spec=Message)
    chat = MagicMock(spec=Chat)
    user = MagicMock(spec=User)
    
    chat.id = 123456789
    user.id = 987654321
    message.chat = chat
    message.from_user = user
    update.message = message
    update.effective_chat = chat
    
    # Mock async methods
    update.message.reply_text = AsyncMock()
    update.message.edit_text = AsyncMock()
    
    return update

@pytest.fixture
def mock_context():
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {}
    return context

# URL Validation Tests
@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", True),
    ("https://youtu.be/dQw4w9WgXcQ", True),
    ("http://example.com", True),
    ("not_a_url", False),
    ("http://.com", False),
    ("https://", False),
    ("", False),
])
def test_url_validation(url, expected):
    assert is_valid_url(url) == expected

# Platform Tests
@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", True),
    ("https://youtu.be/dQw4w9WgXcQ", True),
    ("https://www.facebook.com/video/123", True),
    ("https://www.instagram.com/p/123", True),
    ("https://twitter.com/user/status/123", True),
    ("https://x.com/user/status/123", True),
    ("https://www.tiktok.com/@user/video/123", True),
    ("https://example.com", False),
    ("not_a_url", False),
])
def test_preferred_platform(url, expected):
    assert is_preferred_platform(url) == expected

# Thank You Message Tests
@pytest.mark.parametrize("text,expected", [
    ("תודה", True),
    ("תודה רבה!", True),
    ("thanks", True),
    ("thank you", True),
    ("thx", True),
    ("תנקס", True),
    ("hello", False),
    ("", False),
])
def test_thank_you_detection(text, expected):
    assert is_thank_you_message(text) == expected

# Command Tests
@pytest.mark.asyncio
async def test_start_command(mock_update, mock_context):
    await start(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    assert "שלום!" in mock_update.message.reply_text.call_args[0][0]

# Format Selection Tests
@pytest.mark.asyncio
async def test_ask_format_with_valid_youtube_url(mock_update, mock_context):
    mock_update.message.text = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    await ask_format(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    assert isinstance(mock_update.message.reply_text.call_args[1]['reply_markup'], InlineKeyboardMarkup)

@pytest.mark.asyncio
async def test_ask_format_with_invalid_url(mock_update, mock_context):
    mock_update.message.text = "not_a_url"
    await ask_format(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    assert "אנא שלח קישור תקין" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_ask_format_with_multiple_urls(mock_update, mock_context):
    mock_update.message.text = """
    https://www.youtube.com/watch?v=1234
    https://www.youtube.com/watch?v=5678
    """
    await ask_format(mock_update, mock_context)
    assert mock_update.message.reply_text.call_count == 2
    assert "זיהיתי מספר קישורים" in mock_update.message.reply_text.call_args_list[0][0][0]

# Edge Cases Tests
@pytest.mark.asyncio
async def test_ask_format_with_empty_message(mock_update, mock_context):
    mock_update.message.text = None
    mock_update.message.caption = None
    mock_update.message.photo = None
    mock_update.message.video = None
    mock_update.message.audio = None
    mock_update.message.voice = None
    mock_update.message.document = None
    mock_update.message.sticker = None
    await ask_format(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    assert "אנא שלח קישור תקין" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_ask_format_with_thank_you_and_url(mock_update, mock_context):
    mock_update.message.text = "תודה https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    await ask_format(mock_update, mock_context)
    assert mock_update.message.reply_text.call_count == 2

# Media Message Tests
@pytest.mark.asyncio
async def test_ask_format_with_photo_and_caption(mock_update, mock_context):
    mock_update.message.text = None
    mock_update.message.photo = [MagicMock()]
    mock_update.message.caption = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    await ask_format(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    assert isinstance(mock_update.message.reply_text.call_args[1]['reply_markup'], InlineKeyboardMarkup)

@pytest.mark.asyncio
async def test_ask_format_with_video_no_caption(mock_update, mock_context):
    mock_update.message.text = None
    mock_update.message.video = MagicMock()
    mock_update.message.caption = None
    await ask_format(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    assert "אנא שלח קישור תקין" in mock_update.message.reply_text.call_args[0][0]

# Button Click Tests
@pytest.mark.asyncio
async def test_button_click_audio(mock_update, mock_context):
    mock_update.callback_query = AsyncMock()
    mock_update.callback_query.data = "audio"
    mock_update.callback_query.message = MagicMock()
    mock_update.callback_query.message.edit_text = AsyncMock()
    mock_context.user_data = {
        'current_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        'is_youtube': True
    }
    
    with patch('bot_handlers.download_with_quality') as mock_download:
        mock_download.return_value = AsyncMock()
        await button_click(mock_update, mock_context)
        mock_download.assert_called_once()

@pytest.mark.asyncio
async def test_button_click_video_youtube(mock_update, mock_context):
    mock_update.callback_query = AsyncMock()
    mock_update.callback_query.data = "video"
    mock_update.callback_query.message = MagicMock()
    mock_update.callback_query.message.edit_text = AsyncMock()
    mock_context.user_data = {
        'current_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        'is_youtube': True
    }
    
    await button_click(mock_update, mock_context)
    mock_update.callback_query.message.edit_text.assert_called_once_with(
        'באיזו איכות להוריד את הוידאו?',
        reply_markup=mock_update.callback_query.message.edit_text.call_args[1]['reply_markup']
    )

# Thank You Handler Tests
@pytest.mark.asyncio
async def test_thank_you_handler(mock_update, mock_context):
    await handle_thank_you(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    response = mock_update.message.reply_text.call_args[0][0]
    assert any(resp in response for resp in [
        "בכיף!", "שמח לעזור!", "אין בעד מה!",
        "תהנה/י!", "לשירותך!", "בשמחה!"
    ]) 