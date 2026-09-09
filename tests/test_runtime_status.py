from datetime import datetime, timezone
from unittest.mock import MagicMock

from runtime_status import (
    RLM,
    format_docker_line,
    format_duration_he,
    format_status_message,
    get_docker_api_status,
    parse_docker_started_at,
    read_git_info,
)


def test_format_duration_he_units():
    assert format_duration_he(None) == 'לא ידוע'
    assert format_duration_he(0) == '0 שניות'
    assert format_duration_he(1) == '1 שנייה'
    assert format_duration_he(5) == '5 שניות'
    assert format_duration_he(65) == '1 דקה'
    assert format_duration_he(3661) == '1 שעה, 1 דקה'
    assert format_duration_he(90061) == '1 יום, 1 שעה, 1 דקה'
    assert format_duration_he(172800) == '2 ימים'


def test_format_status_idle_and_git():
    text = format_status_message(
        host_uptime=86400,
        service_uptime=120,
        git_info={'hash': 'abc1234', 'subject': 'Add /status', 'dirty': False},
        version='0.13.1',
        queue_snapshot={'running': False, 'running_elapsed': None, 'waiting': 0},
        maintenance=False,
        local_api=True,
        max_file_size=2 * 1024 * 1024 * 1024,
        ytdlp_version='2026.1.1',
    )
    assert 'שרת: 1 יום' in text
    assert 'סרוויס: 2 דקות' in text
    assert '0.13.1 · abc1234' in text
    assert 'Add /status' in text
    assert 'תור: פנוי' in text
    assert 'Local API' in text
    assert 'yt-dlp: 2026.1.1' in text
    assert 'תחזוקה: לא' in text
    assert 'לא נקי' not in text


def test_format_status_keeps_full_commit_message():
    message = (
        'Update Docker status messages to include Hebrew prefix for consistency.\n'
        'Modified the format_docker_line helper.'
    )
    text = format_status_message(
        host_uptime=10,
        service_uptime=10,
        git_info={'hash': 'abc1234', 'subject': message, 'dirty': False},
        version='0.13.1',
        queue_snapshot={'running': False, 'running_elapsed': None, 'waiting': 0},
    )
    assert message in text
    assert 'Modif...' not in text


def test_format_status_queue_and_dirty_and_maintenance():
    text = format_status_message(
        host_uptime=10,
        service_uptime=10,
        git_info={'hash': 'deadbee', 'subject': 'wip', 'dirty': True},
        version='0.13.1',
        queue_snapshot={'running': True, 'running_elapsed': 45, 'waiting': 2},
        maintenance=True,
        local_api=False,
        max_file_size=50 * 1024 * 1024,
        ytdlp_version=None,
    )
    assert 'הורדה פעילה (כבר 45 שניות)' in text
    assert 'ממתינות: 2' in text
    assert 'עץ עבודה לא נקי' in text
    assert 'תחזוקה: כן' in text
    assert '50MB' in text


def test_format_status_includes_docker_uptime():
    text = format_status_message(
        host_uptime=10,
        service_uptime=10,
        git_info={'hash': 'abc1234', 'subject': 'x', 'dirty': False},
        version='0.13.1',
        queue_snapshot={'running': False, 'running_elapsed': None, 'waiting': 0},
        docker_status={
            'found': True,
            'running': True,
            'uptime_seconds': 3661,
            'status': 'running',
            'error': None,
        },
    )
    assert f'ה-Docker:{RLM} 1 שעה, 1 דקה' in text


def test_format_docker_line_states():
    assert format_docker_line(None) is None
    assert format_docker_line({'error': 'no_docker'}) == f'ה-Docker:{RLM} לא מותקן'
    assert format_docker_line({'error': 'permission'}) == f'ה-Docker:{RLM} אין הרשאה'
    assert format_docker_line({'error': 'not_found', 'found': False}) == f'ה-Docker:{RLM} אין קונטיינר'
    assert format_docker_line({
        'found': True,
        'running': False,
        'status': 'exited',
        'error': None,
    }) == f'ה-Docker:{RLM} לא רץ (exited)'


def test_parse_docker_started_at_rfc3339():
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
    assert int(parse_docker_started_at('2026-09-09T10:58:59.123456789Z', now=now)) == 3660
    assert parse_docker_started_at('0001-01-01T00:00:00Z') is None
    assert parse_docker_started_at('not-a-date') is None


def test_get_docker_api_status_running(monkeypatch):
    result = MagicMock()
    result.returncode = 0
    result.stdout = 'true\trunning\t2026-09-09T10:00:00.123456789Z\n'
    result.stderr = ''
    monkeypatch.setattr('runtime_status.subprocess.run', lambda *a, **k: result)
    monkeypatch.setattr(
        'runtime_status.parse_docker_started_at',
        lambda value, now=None: 99,
    )
    info = get_docker_api_status()
    assert info['found'] is True
    assert info['running'] is True
    assert info['uptime_seconds'] == 99
    assert info['error'] is None


def test_get_docker_api_status_missing_container(monkeypatch):
    result = MagicMock()
    result.returncode = 1
    result.stdout = ''
    result.stderr = 'Error: No such object: telegram-bot-api\n'
    monkeypatch.setattr('runtime_status.subprocess.run', lambda *a, **k: result)
    info = get_docker_api_status()
    assert info['found'] is False
    assert info['error'] == 'not_found'


def test_get_docker_api_status_no_binary(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError('docker')
    monkeypatch.setattr('runtime_status.subprocess.run', boom)
    info = get_docker_api_status()
    assert info['error'] == 'no_docker'


def test_read_git_info_from_this_repo():
    info = read_git_info()
    assert info['hash']
    assert len(info['hash']) >= 7
