"""שמירת הגדרות משתמש בין הפעלות הבוט (JSON פשוט, בלי DB)."""
import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from logger_setup import logger
from config import CHANNEL_WATCH_MAX_PER_USER, CHANNEL_WATCH_NOTIFIED_CAP

DATA_DIR = Path('data')
SEARCH_MODES_FILE = DATA_DIR / 'search_modes.json'
CHANNEL_SUBS_FILE = DATA_DIR / 'channel_subscriptions.json'
KNOWN_CHATS_FILE = DATA_DIR / 'known_chats.json'

VALID_SOURCES = ('videos', 'shorts')
VALID_DELIVERY = ('audio', 'video')

_lock = threading.Lock()
_subs_lock = threading.Lock()
_chats_lock = threading.Lock()


def _ensure_data_dir():
    DATA_DIR.mkdir(exist_ok=True)


def _read_search_modes() -> dict:
    if not SEARCH_MODES_FILE.exists():
        return {}
    try:
        with open(SEARCH_MODES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        logger.warning(f"Could not read search modes file: {e}")
    return {}


def _write_search_modes(data: dict):
    _ensure_data_dir()
    tmp_path = SEARCH_MODES_FILE.with_suffix('.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(SEARCH_MODES_FILE)


def get_search_mode(user_id) -> bool:
    """מחזיר אם מצב חיפוש דלוק למשתמש (ברירת מחדל: כבוי)."""
    with _lock:
        data = _read_search_modes()
        return bool(data.get(str(user_id), False))


def set_search_mode(user_id, enabled: bool):
    """שומר מצב חיפוש למשתמש. כבוי = מוחק מהקובץ כדי לא לנפח אותו."""
    with _lock:
        data = _read_search_modes()
        key = str(user_id)
        if enabled:
            data[key] = True
        else:
            data.pop(key, None)
        try:
            _write_search_modes(data)
        except Exception as e:
            logger.error(f"Could not save search mode for user {user_id}: {e}")
            raise


def _empty_known_user():
    return {
        'username': '',
        'first_name': '',
        'last_name': '',
        'last_seen': None,
    }


def _coerce_known_chats(data) -> dict:
    """רשימה ישנה של IDs → מילון. מילון קיים נשאר."""
    if isinstance(data, list):
        return {str(item): _empty_known_user() for item in data}
    if not isinstance(data, dict):
        return {}
    store = {}
    for key, value in data.items():
        record = _empty_known_user()
        if isinstance(value, dict):
            record['username'] = str(value.get('username') or '')
            record['first_name'] = str(value.get('first_name') or '')
            record['last_name'] = str(value.get('last_name') or '')
            record['last_seen'] = value.get('last_seen')
        store[str(key)] = record
    return store


def _clean_name(value) -> str:
    if not isinstance(value, str):
        return ''
    return value.strip()


def _profile_from_telegram(user=None, chat=None) -> dict:
    first = ''
    last = ''
    username = ''
    if user is not None:
        first = _clean_name(getattr(user, 'first_name', None))
        last = _clean_name(getattr(user, 'last_name', None))
        username = _clean_name(getattr(user, 'username', None))
    if chat is not None:
        first = first or _clean_name(getattr(chat, 'first_name', None))
        last = last or _clean_name(getattr(chat, 'last_name', None))
        username = username or _clean_name(getattr(chat, 'username', None))
        title = _clean_name(getattr(chat, 'title', None))
        if title and not first:
            first = title
    return {
        'username': username.lstrip('@'),
        'first_name': first,
        'last_name': last,
    }


def format_known_user_label(chat_id, record=None) -> str:
    """שם לתצוגה אדמין. בלי רשומה / תקלה — רק המספר, בלי לזרוק."""
    fallback = str(chat_id)
    try:
        if record is None:
            with _chats_lock:
                record = _read_known_chats().get(str(chat_id), {})
        if not isinstance(record, dict):
            record = {}
        first = str(record.get('first_name') or '').strip()
        last = str(record.get('last_name') or '').strip()
        username = str(record.get('username') or '').strip().lstrip('@')
        name = ' '.join(part for part in (first, last) if part)
        if name and username:
            return f'{name} (@{username})'
        if name:
            return name
        if username:
            return f'@{username}'
        return fallback
    except Exception:
        return fallback


def _read_known_chats() -> dict:
    if not KNOWN_CHATS_FILE.exists():
        return {}
    try:
        with open(KNOWN_CHATS_FILE, 'r', encoding='utf-8') as f:
            return _coerce_known_chats(json.load(f))
    except Exception as e:
        logger.warning(f"Could not read known chats file: {e}")
        return {}


def _write_known_chats(store: dict):
    _ensure_data_dir()
    tmp_path = KNOWN_CHATS_FILE.with_suffix('.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    tmp_path.replace(KNOWN_CHATS_FILE)


def remember_chat(chat_id, user=None, chat=None):
    """שומר chat_id + שם אם יש, לכל מי שדיבר עם הבוט."""
    with _chats_lock:
        store = _read_known_chats()
        key = str(chat_id)
        record = store.get(key) or _empty_known_user()
        profile = _profile_from_telegram(user=user, chat=chat)
        changed = key not in store
        for field, value in profile.items():
            if value and record.get(field) != value:
                record[field] = value
                changed = True
        seen = datetime.now(timezone.utc).isoformat()
        if record.get('last_seen') != seen:
            record['last_seen'] = seen
            changed = True
        if changed:
            store[key] = record
            try:
                _write_known_chats(store)
            except Exception as e:
                logger.warning(f"Could not save known chat {chat_id}: {e}")


def remember_from_update(update):
    """לוכד ID+שם מכל עדכון טלגרם (הודעה או לחיצת כפתור)."""
    if update is None:
        return
    chat = getattr(update, 'effective_chat', None)
    user = getattr(update, 'effective_user', None)
    query = getattr(update, 'callback_query', None)
    if chat is None and query is not None and getattr(query, 'message', None) is not None:
        chat = query.message.chat
    if user is None and query is not None:
        user = getattr(query, 'from_user', None)
    if chat is None:
        return
    remember_chat(chat.id, user=user, chat=chat)


def list_known_chat_ids():
    """chat_ids שכבר דיברו עם הבוט (תפריט, חיפוש, או מעקב ערוצים)."""
    ids = set()
    with _chats_lock:
        ids.update(_read_known_chats().keys())
    with _lock:
        ids.update(_read_search_modes().keys())
    with _subs_lock:
        ids.update(_read_subs_store()['users'].keys())
    return list(ids)


def _empty_subs_store():
    return {'last_run_at': None, 'users': {}}


def _read_subs_store() -> dict:
    if not CHANNEL_SUBS_FILE.exists():
        return _empty_subs_store()
    try:
        with open(CHANNEL_SUBS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty_subs_store()
        data.setdefault('last_run_at', None)
        users = data.get('users')
        if not isinstance(users, dict):
            data['users'] = {}
        return data
    except Exception as e:
        logger.warning(f"Could not read channel subscriptions file: {e}")
        return _empty_subs_store()


def _write_subs_store(data: dict):
    _ensure_data_dir()
    tmp_path = CHANNEL_SUBS_FILE.with_suffix('.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(CHANNEL_SUBS_FILE)


def normalize_source_list(sources):
    cleaned = []
    for source in sources or []:
        if source in VALID_SOURCES and source not in cleaned:
            cleaned.append(source)
    return cleaned or ['videos']


def normalize_delivery_list(delivery):
    cleaned = []
    for item in delivery or []:
        if item in VALID_DELIVERY and item not in cleaned:
            cleaned.append(item)
    return cleaned or ['audio']


def _empty_source_state():
    return {
        'last_seen_video_id': None,
        'last_seen_title': None,
        'seen_video_ids': [],
    }


def _normalize_source_state(src) -> dict:
    if not isinstance(src, dict):
        return _empty_source_state()
    normalized = dict(src)
    normalized.setdefault('last_seen_video_id', None)
    normalized.setdefault('last_seen_title', None)
    seen = normalized.get('seen_video_ids')
    if not isinstance(seen, list):
        normalized['seen_video_ids'] = []
    return normalized


def _protected_video_ids(sub: dict) -> set:
    """ID-ים מהחלון האחרון — אסור שייחתכו ב-cap של notified."""
    protected = set()
    for src in (sub.get('sources_state') or {}).values():
        if not isinstance(src, dict):
            continue
        for video_id in src.get('seen_video_ids') or []:
            if video_id:
                protected.add(video_id)
    return protected


def _trim_notified_video_ids(sub: dict):
    notified = list(sub.get('notified_video_ids') or [])
    if len(notified) <= CHANNEL_WATCH_NOTIFIED_CAP:
        return
    protected = _protected_video_ids(sub)
    trimmed = notified[-CHANNEL_WATCH_NOTIFIED_CAP:]
    have = set(trimmed)
    for video_id in protected:
        if video_id not in have:
            trimmed.append(video_id)
            have.add(video_id)
    sub['notified_video_ids'] = trimmed


def _normalize_sub(sub: dict) -> dict:
    normalized = deepcopy(sub)
    normalized['sources'] = normalize_source_list(normalized.get('sources'))
    normalized['delivery'] = normalize_delivery_list(normalized.get('delivery'))
    normalized['include_description'] = bool(normalized.get('include_description'))
    normalized.setdefault('channel_url', '')
    normalized.setdefault('channel_id', '')
    normalized.setdefault('channel_label', '')
    normalized.setdefault('initialized_at', None)
    normalized.setdefault('notified_video_ids', [])
    sources_state = normalized.get('sources_state')
    if not isinstance(sources_state, dict):
        sources_state = {}
    for source in VALID_SOURCES:
        sources_state[source] = _normalize_source_state(sources_state.get(source))
    normalized['sources_state'] = sources_state
    return normalized


def list_channel_subs(user_id) -> list:
    with _subs_lock:
        store = _read_subs_store()
        return [_normalize_sub(sub) for sub in store['users'].get(str(user_id), [])]


def get_channel_sub(user_id, index: int):
    subs = list_channel_subs(user_id)
    if index < 0 or index >= len(subs):
        return None
    return subs[index]


def find_duplicate_channel(user_id, channel_id='', channel_url=''):
    """מחזיר אינדקס אם הערוץ כבר במעקב, אחרת None."""
    channel_id = (channel_id or '').strip()
    channel_url = (channel_url or '').rstrip('/').lower()
    for index, sub in enumerate(list_channel_subs(user_id)):
        if channel_id and sub.get('channel_id') == channel_id:
            return index
        if channel_url and (sub.get('channel_url') or '').rstrip('/').lower() == channel_url:
            return index
    return None


def add_channel_sub(user_id, sub: dict):
    """מוסיף מעקב. מחזיר (index, None) או (None, סיבת-שגיאה)."""
    normalized = _normalize_sub(sub)
    with _subs_lock:
        store = _read_subs_store()
        key = str(user_id)
        current = [_normalize_sub(item) for item in store['users'].get(key, [])]
        if len(current) >= CHANNEL_WATCH_MAX_PER_USER:
            return None, 'limit'
        for existing in current:
            if normalized.get('channel_id') and existing.get('channel_id') == normalized['channel_id']:
                return None, 'duplicate'
            if (
                normalized.get('channel_url')
                and (existing.get('channel_url') or '').rstrip('/').lower()
                == (normalized.get('channel_url') or '').rstrip('/').lower()
            ):
                return None, 'duplicate'
        if not normalized.get('initialized_at'):
            normalized['initialized_at'] = datetime.now(timezone.utc).isoformat()
        current.append(normalized)
        store['users'][key] = current
        _write_subs_store(store)
        return len(current) - 1, None


def update_channel_sub(user_id, index: int, **fields):
    with _subs_lock:
        store = _read_subs_store()
        key = str(user_id)
        current = [_normalize_sub(item) for item in store['users'].get(key, [])]
        if index < 0 or index >= len(current):
            return None
        current[index].update(fields)
        current[index] = _normalize_sub(current[index])
        _trim_notified_video_ids(current[index])
        store['users'][key] = current
        _write_subs_store(store)
        return current[index]


def remove_channel_sub(user_id, index: int) -> bool:
    with _subs_lock:
        store = _read_subs_store()
        key = str(user_id)
        current = list(store['users'].get(key, []))
        if index < 0 or index >= len(current):
            return False
        current.pop(index)
        if current:
            store['users'][key] = current
        else:
            store['users'].pop(key, None)
        _write_subs_store(store)
        return True


def iter_all_channel_subs():
    """מחזיר [(user_id_str, index, sub), ...] לכל המעקבים."""
    with _subs_lock:
        store = _read_subs_store()
        items = []
        for user_id, subs in store['users'].items():
            for index, sub in enumerate(subs):
                items.append((user_id, index, _normalize_sub(sub)))
        return items


def get_channel_watch_last_run():
    with _subs_lock:
        return _read_subs_store().get('last_run_at')


def set_channel_watch_last_run(timestamp: str):
    with _subs_lock:
        store = _read_subs_store()
        store['last_run_at'] = timestamp
        _write_subs_store(store)
