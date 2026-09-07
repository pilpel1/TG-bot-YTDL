"""בדיקות אינטגרציה: ה-cache בפועל בתוך download_with_quality.

בודק שלושה תרחישים:
1. cache hit -> נשלח file_id ישירות, yt-dlp לא נוגע בכלל.
2. cache hit עם file_id מת -> הרשומה נמחקת, וממשיכים ל-fallback (הורדה אמיתית).
3. הורדה אמיתית שמצליחה -> נשמר file_id חדש ל-cache.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import download_cache
import download_manager

AUDIO_QUALITY = {'format': 'bestaudio', 'quality_name': 'audio-only'}
VIDEO_QUALITY = {'format': 'best[height<=720]', 'quality_name': 'regular'}
URL = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'


@pytest.fixture(autouse=True)
def _tmp_cache_db(tmp_path, monkeypatch):
    monkeypatch.setattr(download_cache, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(download_cache, 'DB_PATH', tmp_path / 'cache.db')
    download_cache._local.conn = None
    yield
    conn = getattr(download_cache._local, 'conn', None)
    if conn is not None:
        conn.close()
    download_cache._local.conn = None


def make_status_message(chat_id=555):
    bot = MagicMock()
    bot.send_audio = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_message = AsyncMock()

    status_message = MagicMock()
    status_message.chat_id = chat_id
    status_message.chat = MagicMock(username='tester', first_name=None)
    status_message.edit_text = AsyncMock()
    status_message.reply_text = AsyncMock()
    status_message.delete = AsyncMock()
    status_message.get_bot.return_value = bot
    return status_message, bot


def make_context():
    context = MagicMock()
    context.user_data = {}
    return context


@pytest.mark.asyncio
async def test_cache_hit_sends_file_id_without_touching_yt_dlp():
    download_cache.save_cached_file(
        URL, 'audio', AUDIO_QUALITY['quality_name'], 'CACHED_FILE_ID', title='Cached Song'
    )
    status_message, bot = make_status_message()
    context = make_context()

    with patch('download_manager.yt_dlp.YoutubeDL') as mock_ydl_class:
        result = await download_manager.download_with_quality(
            context, status_message, URL, 'audio', AUDIO_QUALITY, None
        )

    mock_ydl_class.assert_not_called()
    bot.send_audio.assert_awaited_once()
    assert bot.send_audio.call_args.kwargs['audio'] == 'CACHED_FILE_ID'
    assert result is None
    status_message.delete.assert_awaited_once()
    # ההודעה שנשלחה בסוף מציינת שזה הגיע מהמטמון
    completion_text = bot.send_message.call_args.kwargs['text']
    assert 'מטמון' in completion_text


@pytest.mark.asyncio
async def test_cache_hit_video_sends_by_file_id():
    download_cache.save_cached_file(
        URL, 'video', VIDEO_QUALITY['quality_name'], 'CACHED_VIDEO_ID'
    )
    status_message, bot = make_status_message()
    context = make_context()

    with patch('download_manager.yt_dlp.YoutubeDL') as mock_ydl_class:
        result = await download_manager.download_with_quality(
            context, status_message, URL, 'video', VIDEO_QUALITY, None
        )

    mock_ydl_class.assert_not_called()
    bot.send_video.assert_awaited_once()
    assert bot.send_video.call_args.kwargs['video'] == 'CACHED_VIDEO_ID'
    assert result is None


@pytest.mark.asyncio
async def test_dead_file_id_is_evicted_and_falls_back_to_real_download():
    download_cache.save_cached_file(URL, 'audio', AUDIO_QUALITY['quality_name'], 'DEAD_FILE_ID')

    status_message, bot = make_status_message()
    bot.send_audio.side_effect = Exception('Wrong file identifier/HTTP URL specified')
    context = make_context()

    with patch('download_manager.yt_dlp.YoutubeDL') as mock_ydl_class:
        mock_ydl = MagicMock()
        mock_ydl.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = Exception('network is down, stop test here')
        mock_ydl_class.return_value = mock_ydl

        with pytest.raises(Exception):
            await download_manager.download_with_quality(
                context, status_message, URL, 'audio', AUDIO_QUALITY, None
            )

    # ה-file_id המת הוסר מה-cache
    assert download_cache.get_cached_file(URL, 'audio', AUDIO_QUALITY['quality_name']) is None
    # וניסינו fallback אמיתי דרך yt-dlp (לא רק ויתרנו)
    mock_ydl_class.assert_called()


@pytest.mark.asyncio
async def test_successful_download_saves_file_id_to_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(download_manager, 'is_ffmpeg_available', lambda: False)
    monkeypatch.setattr(download_manager, 'estimate_media_size', lambda info: (1000, False))
    monkeypatch.setattr(download_manager, 'log_download', MagicMock())

    downloaded_file = tmp_path / 'dQw4w9WgXcQ.m4a'
    downloaded_file.write_bytes(b'fake audio bytes')

    fake_info = {'id': 'dQw4w9WgXcQ', 'title': 'Never Gonna Give You Up', 'uploader': 'RickAstleyVEVO', 'ext': 'm4a'}

    status_message, bot = make_status_message()
    bot.send_audio.return_value = MagicMock(audio=MagicMock(file_id='NEW_FILE_ID'))
    context = make_context()

    with patch('download_manager.yt_dlp.YoutubeDL') as mock_ydl_class:
        mock_ydl = MagicMock()
        mock_ydl.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = fake_info
        mock_ydl.prepare_filename.return_value = str(downloaded_file)
        mock_ydl_class.return_value = mock_ydl

        result = await download_manager.download_with_quality(
            context, status_message, URL, 'audio', AUDIO_QUALITY, None
        )

    assert result is None
    bot.send_audio.assert_awaited_once()

    cached = download_cache.get_cached_file(URL, 'audio', AUDIO_QUALITY['quality_name'])
    assert cached == {'file_id': 'NEW_FILE_ID', 'title': 'Never Gonna Give You Up'}
