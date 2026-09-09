from types import SimpleNamespace

from logger_setup import format_requester_for_log


def test_format_requester_includes_name_and_chat_id():
    chat = SimpleNamespace(
        id=770847605,
        username=None,
        first_name='Dana',
        last_name='Cohen',
        title=None,
    )
    assert format_requester_for_log(chat) == 'Dana Cohen (chat_id=770847605)'


def test_format_requester_prefers_username_with_full_name():
    chat = SimpleNamespace(
        id=11,
        username='dvir',
        first_name='Dvir',
        last_name='',
        title=None,
    )
    assert format_requester_for_log(chat) == 'Dvir (@dvir) (chat_id=11)'


def test_format_requester_falls_back_to_chat_id_only():
    assert format_requester_for_log(None, chat_id=42) == 'chat_id=42'


def test_format_requester_uses_explicit_chat_id_when_chat_id_attr_is_garbage():
    chat = SimpleNamespace(
        id=object(),
        username=None,
        first_name='A',
        last_name='C',
        title=None,
    )
    assert format_requester_for_log(chat, chat_id=99) == 'A C (chat_id=99)'
