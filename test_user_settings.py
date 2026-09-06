import json
from pathlib import Path
from user_settings import (
    get_search_mode,
    set_search_mode,
    add_channel_sub,
    list_channel_subs,
    update_channel_sub,
    remove_channel_sub,
    find_duplicate_channel,
    get_channel_watch_last_run,
    set_channel_watch_last_run,
    iter_all_channel_subs,
)
import user_settings


def test_search_mode_persists_across_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(user_settings, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(user_settings, 'SEARCH_MODES_FILE', tmp_path / 'search_modes.json')

    assert get_search_mode(111) is False
    set_search_mode(111, True)
    assert get_search_mode(111) is True
    assert get_search_mode(222) is False

    set_search_mode(111, False)
    assert get_search_mode(111) is False
    # כבוי = לא נשמר בקובץ
    data = json.loads(Path(tmp_path / 'search_modes.json').read_text(encoding='utf-8'))
    assert '111' not in data


def _subs_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(user_settings, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(user_settings, 'CHANNEL_SUBS_FILE', tmp_path / 'channel_subscriptions.json')


def _sample_sub(label='Foo', channel_id='UCaaa'):
    return {
        'channel_url': f'https://www.youtube.com/@{label.lower()}',
        'channel_id': channel_id,
        'channel_label': label,
        'sources': ['videos'],
        'delivery': ['audio'],
        'include_description': False,
    }


def test_channel_sub_crud_and_duplicate(tmp_path, monkeypatch):
    _subs_tmp(tmp_path, monkeypatch)
    index, error = add_channel_sub(7, _sample_sub())
    assert error is None
    assert index == 0
    assert list_channel_subs(7)[0]['channel_label'] == 'Foo'

    _, error = add_channel_sub(7, _sample_sub())
    assert error == 'duplicate'
    assert find_duplicate_channel(7, channel_id='UCaaa') == 0

    updated = update_channel_sub(7, 0, delivery=['audio', 'video'], include_description=True)
    assert updated['delivery'] == ['audio', 'video']
    assert updated['include_description'] is True

    assert remove_channel_sub(7, 0) is True
    assert list_channel_subs(7) == []
    assert find_duplicate_channel(7, channel_id='UCaaa') is None


def test_channel_sub_max_limit(tmp_path, monkeypatch):
    _subs_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(user_settings, 'CHANNEL_WATCH_MAX_PER_USER', 2)
    assert add_channel_sub(1, _sample_sub('A', 'UCa'))[1] is None
    assert add_channel_sub(1, _sample_sub('B', 'UCb'))[1] is None
    _, error = add_channel_sub(1, _sample_sub('C', 'UCc'))
    assert error == 'limit'


def test_channel_watch_last_run_and_iter(tmp_path, monkeypatch):
    _subs_tmp(tmp_path, monkeypatch)
    assert get_channel_watch_last_run() is None
    add_channel_sub(1, _sample_sub('A', 'UCa'))
    add_channel_sub(2, _sample_sub('B', 'UCb'))
    set_channel_watch_last_run('2026-09-06T08:00:00+00:00')
    assert get_channel_watch_last_run() == '2026-09-06T08:00:00+00:00'
    items = iter_all_channel_subs()
    assert {(user_id, sub['channel_label']) for user_id, _, sub in items} == {
        ('1', 'A'),
        ('2', 'B'),
    }
