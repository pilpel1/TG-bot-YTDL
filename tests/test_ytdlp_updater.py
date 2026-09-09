from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ytdlp_updater import (
    YtdlpUpdateManager,
    fetch_latest_ytdlp_version,
    get_installed_ytdlp_version,
    has_inflight_metadata,
    is_maintenance_mode,
    is_newer_ytdlp_version,
    parse_ytdlp_version,
    seconds_until_next_check,
    set_maintenance_mode,
    track_ytdlp_metadata,
    write_pending_update_flag,
)


@pytest.fixture(autouse=True)
def reset_maintenance_flag():
    set_maintenance_mode(False)
    yield
    set_maintenance_mode(False)


def test_parse_ytdlp_version_ignores_non_numeric_suffix():
    assert parse_ytdlp_version('2026.8.19') == (2026, 8, 19)
    assert parse_ytdlp_version('2026.08.19.233646') == (2026, 8, 19, 233646)


def test_is_newer_ytdlp_version():
    assert is_newer_ytdlp_version('2026.8.20', '2026.8.19')
    assert not is_newer_ytdlp_version('2026.8.19', '2026.8.19')
    assert not is_newer_ytdlp_version('2026.8.18', '2026.8.19')
    assert not is_newer_ytdlp_version('', '2026.8.19')


def test_seconds_until_next_check_same_day_before_hour():
    now = datetime(2026, 9, 2, 0, 30, 0)
    with patch('ytdlp_updater.YTDLP_UPDATE_HOUR', 1), \
         patch('ytdlp_updater.get_update_timezone', return_value=now.astimezone().tzinfo):
        delay = seconds_until_next_check(now.replace(tzinfo=now.astimezone().tzinfo))
    assert 29 * 60 <= delay <= 31 * 60


def test_seconds_until_next_check_after_hour_waits_until_tomorrow():
    now = datetime(2026, 9, 2, 1, 5, 0)
    tz = now.astimezone().tzinfo
    with patch('ytdlp_updater.YTDLP_UPDATE_HOUR', 1), \
         patch('ytdlp_updater.get_update_timezone', return_value=tz):
        delay = seconds_until_next_check(now.replace(tzinfo=tz))
    assert delay > 23 * 3600


def test_write_pending_update_flag(tmp_path):
    flag = tmp_path / 'pending_ytdlp_update'
    write_pending_update_flag('2026.9.1', flag_path=flag)
    assert flag.read_text(encoding='utf-8').strip() == '2026.9.1'


def test_get_installed_ytdlp_version_returns_a_string():
    version = get_installed_ytdlp_version()
    assert isinstance(version, str)
    assert version


def test_track_ytdlp_metadata_counts_and_resets():
    assert not has_inflight_metadata()
    with track_ytdlp_metadata():
        assert has_inflight_metadata()
    assert not has_inflight_metadata()


def test_fetch_latest_ytdlp_version_reads_pypi_json():
    fake = MagicMock()
    fake.json.return_value = {'info': {'version': '2026.9.1'}}
    fake.raise_for_status = MagicMock()
    with patch('ytdlp_updater.requests.get', return_value=fake) as mock_get:
        assert fetch_latest_ytdlp_version() == '2026.9.1'
    assert mock_get.call_args[0][0] == 'https://pypi.org/pypi/yt-dlp/json'


@pytest.mark.asyncio
async def test_run_check_does_nothing_when_already_latest(tmp_path):
    application = MagicMock()
    application.bot_data = {'download_queue': MagicMock(is_idle=MagicMock(return_value=True))}
    application.stop_running = MagicMock()
    manager = YtdlpUpdateManager(application)

    with patch('ytdlp_updater.get_installed_ytdlp_version', return_value='2026.9.1'), \
         patch('ytdlp_updater.fetch_latest_ytdlp_version', return_value='2026.9.1'):
        found = await manager.run_check()

    assert found is False
    assert not is_maintenance_mode()
    application.stop_running.assert_not_called()


@pytest.mark.asyncio
async def test_run_check_enters_maintenance_and_stops_when_newer(tmp_path):
    queue = MagicMock()
    queue.is_idle.return_value = True
    queue.job_count.return_value = 0
    application = MagicMock()
    application.bot_data = {'download_queue': queue}
    application.stop_running = MagicMock()
    manager = YtdlpUpdateManager(application)
    flag = tmp_path / 'pending_ytdlp_update'

    with patch('ytdlp_updater.get_installed_ytdlp_version', return_value='2026.8.19'), \
         patch('ytdlp_updater.fetch_latest_ytdlp_version', return_value='2026.9.1'), \
         patch('ytdlp_updater.YTDLP_PENDING_UPDATE_FLAG', flag):
        found = await manager.run_check()

    assert found is True
    assert is_maintenance_mode()
    application.stop_running.assert_called_once()
    assert flag.read_text(encoding='utf-8').strip() == '2026.9.1'


@pytest.mark.asyncio
async def test_run_check_timeout_cancels_remaining_jobs(tmp_path):
    queue = MagicMock()
    queue.is_idle.return_value = False
    queue.job_count.return_value = 2
    queue.cancel_all = AsyncMock(return_value=2)
    application = MagicMock()
    application.bot_data = {'download_queue': queue}
    application.stop_running = MagicMock()
    manager = YtdlpUpdateManager(application)
    flag = tmp_path / 'pending_ytdlp_update'

    with patch('ytdlp_updater.get_installed_ytdlp_version', return_value='2026.8.19'), \
         patch('ytdlp_updater.fetch_latest_ytdlp_version', return_value='2026.9.1'), \
         patch('ytdlp_updater.YTDLP_PENDING_UPDATE_FLAG', flag), \
         patch('ytdlp_updater.YTDLP_UPDATE_MAX_WAIT_HOURS', 0), \
         patch('ytdlp_updater._POST_TIMEOUT_GRACE_SECONDS', 0), \
         patch('ytdlp_updater._IDLE_POLL_SECONDS', 0):
        found = await manager.run_check()

    assert found is True
    queue.cancel_all.assert_awaited()
    application.stop_running.assert_called_once()

