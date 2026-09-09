import json
from pathlib import Path
from unittest.mock import MagicMock
from user_settings import (
    get_search_mode,
    set_search_mode,
    remember_chat,
    remember_from_update,
    list_known_chat_ids,
    format_known_user_label,
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


def test_update_channel_sub_keeps_seen_ids_when_trimming_notified(tmp_path, monkeypatch):
    _subs_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(user_settings, 'CHANNEL_WATCH_NOTIFIED_CAP', 3)
    add_channel_sub(1, {
        **_sample_sub(),
        'notified_video_ids': ['a', 'b', 'c', 'd'],
        'sources_state': {
            'videos': {
                'last_seen_video_id': 'a',
                'seen_video_ids': ['a', 'z'],
            }
        },
    })
    updated = update_channel_sub(1, 0, notified_video_ids=['a', 'b', 'c', 'd'])
    assert 'd' in updated['notified_video_ids']
    assert 'a' in updated['notified_video_ids']
    assert 'z' in updated['notified_video_ids']


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


def test_known_chats_and_list_includes_search_and_subs(tmp_path, monkeypatch):
    monkeypatch.setattr(user_settings, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(user_settings, 'SEARCH_MODES_FILE', tmp_path / 'search_modes.json')
    monkeypatch.setattr(user_settings, 'CHANNEL_SUBS_FILE', tmp_path / 'channel_subscriptions.json')
    monkeypatch.setattr(user_settings, 'KNOWN_CHATS_FILE', tmp_path / 'known_chats.json')

    remember_chat(111)
    remember_chat(111)
    set_search_mode(222, True)
    add_channel_sub(333, _sample_sub('C', 'UCc'))

    assert set(list_known_chat_ids()) == {'111', '222', '333'}


def test_known_chats_migrates_list_and_stores_names(tmp_path, monkeypatch):
    monkeypatch.setattr(user_settings, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(user_settings, 'SEARCH_MODES_FILE', tmp_path / 'search_modes.json')
    monkeypatch.setattr(user_settings, 'CHANNEL_SUBS_FILE', tmp_path / 'channel_subscriptions.json')
    monkeypatch.setattr(user_settings, 'KNOWN_CHATS_FILE', tmp_path / 'known_chats.json')
    (tmp_path / 'known_chats.json').write_text('["111", "222"]', encoding='utf-8')

    user = MagicMock()
    user.first_name = 'דביר'
    user.last_name = ''
    user.username = 'dvir'
    remember_chat(111, user=user)

    assert format_known_user_label(111) == 'דביר (@dvir)'
    assert format_known_user_label(222) == '222'
    assert format_known_user_label(222, record='bad') == '222'
    assert format_known_user_label(222, record=None) == '222'
    assert set(list_known_chat_ids()) == {'111', '222'}


def test_remember_from_update_uses_effective_user(tmp_path, monkeypatch):
    monkeypatch.setattr(user_settings, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(user_settings, 'KNOWN_CHATS_FILE', tmp_path / 'known_chats.json')
    monkeypatch.setattr(user_settings, 'SEARCH_MODES_FILE', tmp_path / 'search_modes.json')
    monkeypatch.setattr(user_settings, 'CHANNEL_SUBS_FILE', tmp_path / 'channel_subscriptions.json')

    update = MagicMock()
    update.effective_chat.id = 555
    update.effective_user.first_name = 'Noam'
    update.effective_user.last_name = 'R'
    update.effective_user.username = None
    update.callback_query = None
    remember_from_update(update)
    assert format_known_user_label(555) == 'Noam R'
