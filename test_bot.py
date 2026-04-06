import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, Message, Chat, User, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot_handlers import (
    is_valid_url, is_preferred_platform, is_thank_you_message,
    start, ask_format, button_click, handle_thank_you
)
from config import YOUTUBE_QUALITY_LEVELS
from download_manager import (
    extract_max_height_from_format,
    build_youtube_video_format,
    build_youtube_video_fallback_formats,
)
from utils import (
    extract_available_youtube_heights,
    build_youtube_quality_option,
    build_youtube_audio_option,
    estimate_media_size,
    format_file_size,
)

# Fixtures
@pytest.fixture
def mock_update():
    update = MagicMock(spec=Update)
    message = MagicMock(spec=Message)
    status_message = MagicMock(spec=Message)
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
    status_message.edit_text = AsyncMock()
    status_message.reply_text = AsyncMock()
    update.message.reply_text.return_value = status_message
    
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
    with patch('bot_handlers.start_youtube_download_options_prefetch') as mock_prefetch:
        await ask_format(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    assert "מה תרצה להוריד?" in mock_update.message.reply_text.call_args[0][0]
    mock_prefetch.assert_called_once_with(
        mock_context,
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )

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
    with patch('bot_handlers.start_youtube_download_options_prefetch') as mock_prefetch:
        await ask_format(mock_update, mock_context)
    assert mock_update.message.reply_text.call_count == 2
    assert "זיהיתי מספר קישורים" in mock_update.message.reply_text.call_args_list[0][0][0]
    mock_prefetch.assert_called_once()

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
    with patch('bot_handlers.start_youtube_download_options_prefetch'):
        await ask_format(mock_update, mock_context)
    assert mock_update.message.reply_text.call_count == 2

# Media Message Tests
@pytest.mark.asyncio
async def test_ask_format_with_photo_and_caption(mock_update, mock_context):
    mock_update.message.text = None
    mock_update.message.photo = [MagicMock()]
    mock_update.message.caption = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    with patch('bot_handlers.start_youtube_download_options_prefetch'):
        await ask_format(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    assert "מה תרצה להוריד?" in mock_update.message.reply_text.call_args[0][0]

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
        selected_quality = mock_download.call_args[0][4]
        assert selected_quality['download_mode'] == 'audio'
        assert selected_quality['quality_name'] == 'אודיו בלבד 🎵'

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
    with patch('bot_handlers.show_youtube_download_options', new=AsyncMock()) as mock_show_options:
        await button_click(mock_update, mock_context)

    mock_update.callback_query.answer.assert_called_once()
    mock_show_options.assert_awaited_once_with(
        mock_update.callback_query.message,
        mock_context,
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    )


@pytest.mark.asyncio
async def test_ask_format_with_youtube_playlist_starts_prefetch_and_shows_format_buttons(mock_update, mock_context):
    mock_update.message.text = "https://www.youtube.com/playlist?list=PL123"
    with patch('bot_handlers.start_youtube_download_options_prefetch') as mock_prefetch:
        await ask_format(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    assert "מה תרצה להוריד?" in mock_update.message.reply_text.call_args[0][0]
    assert isinstance(mock_update.message.reply_text.call_args[1]['reply_markup'], InlineKeyboardMarkup)
    mock_prefetch.assert_called_once_with(
        mock_context,
        "https://www.youtube.com/playlist?list=PL123"
    )


@pytest.mark.asyncio
async def test_button_click_dynamic_quality_selection_uses_cached_options(mock_update, mock_context):
    mock_update.callback_query = AsyncMock()
    mock_update.callback_query.data = "quality_0"
    mock_update.callback_query.message = MagicMock()
    mock_update.callback_query.message.edit_text = AsyncMock()
    mock_update.callback_query.message.reply_text = AsyncMock()
    mock_context.user_data = {
        'current_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        'download_mode': 'video',
        'youtube_download_options': [build_youtube_quality_option(720)]
    }

    with patch('bot_handlers.download_with_quality') as mock_download:
        mock_download.return_value = AsyncMock()
        await button_click(mock_update, mock_context)

    selected_quality = mock_download.call_args[0][4]
    assert selected_quality['quality_name'] == '720p'
    assert selected_quality['format'].startswith('bestvideo[height<=720]')


@pytest.mark.asyncio
async def test_button_click_blocked_quality_shows_popup(mock_update, mock_context):
    mock_update.callback_query = AsyncMock()
    mock_update.callback_query.data = "quality_0"
    mock_update.callback_query.message = MagicMock()
    mock_update.callback_query.message.reply_text = AsyncMock()
    mock_context.user_data = {
        'current_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        'youtube_download_options': [
            {
                **build_youtube_quality_option(2160),
                'is_blocked': True,
                'estimated_size_bytes': 3 * 1024 * 1024 * 1024,
            },
            {
                **build_youtube_quality_option(1080),
                'is_blocked': False,
                'estimated_size_bytes': 500 * 1024 * 1024,
            },
            {
                **build_youtube_audio_option(),
                'is_blocked': False,
                'estimated_size_bytes': 50 * 1024 * 1024,
            }
        ]
    }

    await button_click(mock_update, mock_context)

    mock_update.callback_query.answer.assert_called_once()
    assert "האיכות הגבוהה ביותר שזמינה: 1080p" in mock_update.callback_query.answer.call_args[0][0]
    assert mock_update.callback_query.answer.call_args[1]['show_alert'] is True


@pytest.mark.asyncio
async def test_button_click_cancel_clears_download_state(mock_update, mock_context):
    mock_update.callback_query = AsyncMock()
    mock_update.callback_query.data = "cancel"
    mock_update.callback_query.message = MagicMock()
    mock_update.callback_query.message.edit_text = AsyncMock()
    mock_context.user_data = {
        'current_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        'youtube_download_options': [build_youtube_quality_option(720)],
        'youtube_prefetch_task': AsyncMock(),
        'youtube_prefetch_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        'current_quality_index': 0,
        'download_mode': 'video',
        'is_youtube': True,
    }

    await button_click(mock_update, mock_context)

    assert mock_context.user_data == {}
    mock_update.callback_query.answer.assert_called_once_with('בוטל')
    mock_update.callback_query.message.edit_text.assert_called_once_with('בוטל. אפשר לשלוח קישור חדש.')


def test_extract_max_height_from_format():
    assert extract_max_height_from_format(YOUTUBE_QUALITY_LEVELS[0]['format']) == 1080
    assert extract_max_height_from_format(YOUTUBE_QUALITY_LEVELS[1]['format']) == 720
    assert extract_max_height_from_format(YOUTUBE_QUALITY_LEVELS[2]['format']) == 480


def test_build_youtube_video_format_keeps_selected_quality_with_ffmpeg():
    with patch('download_manager.is_ffmpeg_available', return_value=True):
        selected_format = YOUTUBE_QUALITY_LEVELS[2]['format']
        assert build_youtube_video_format(selected_format) == selected_format


def test_build_youtube_video_format_uses_progressive_fallback_without_ffmpeg():
    with patch('download_manager.is_ffmpeg_available', return_value=False):
        assert build_youtube_video_format(YOUTUBE_QUALITY_LEVELS[2]['format']) == (
            'best[height<=480][ext=mp4]/best[height<=480]/best[ext=mp4]/best'
        )


def test_build_youtube_video_fallback_formats_respect_requested_height():
    with patch('download_manager.is_ffmpeg_available', return_value=True):
        fallback_formats = build_youtube_video_fallback_formats(480)

    assert fallback_formats[0].startswith('bestvideo[height<=480]')
    assert any('best[height<=480]' in fallback_format for fallback_format in fallback_formats)


def test_extract_available_youtube_heights_filters_and_sorts_formats():
    formats = [
        {'format_id': '399', 'height': 1080, 'vcodec': 'av01', 'ext': 'mp4'},
        {'format_id': '140', 'height': None, 'vcodec': 'none', 'ext': 'm4a'},
        {'format_id': '18', 'height': 360, 'vcodec': 'avc1', 'ext': 'mp4'},
        {'format_id': 'sb0', 'height': 180, 'vcodec': 'none', 'ext': 'mhtml'},
        {'format_id': '135', 'height': 480, 'vcodec': 'avc1', 'ext': 'mp4'},
    ]

    assert extract_available_youtube_heights(formats) == [1080, 480, 360]


def test_build_youtube_quality_option_uses_resolution_label():
    quality_option = build_youtube_quality_option(720)

    assert quality_option['quality_name'] == '720p'
    assert 'height<=720' in quality_option['format']


def test_estimate_media_size_sums_requested_formats():
    info = {
        'requested_formats': [
            {'filesize': 1000},
            {'filesize_approx': 2500},
        ]
    }

    estimated_size, is_approximate = estimate_media_size(info)

    assert estimated_size == 3500
    assert is_approximate is True


def test_format_file_size_formats_gigabytes():
    assert format_file_size(2 * 1024 * 1024 * 1024) == '2.00GB'

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