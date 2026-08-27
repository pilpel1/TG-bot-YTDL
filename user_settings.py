"""שמירת הגדרות משתמש בין הפעלות הבוט (JSON פשוט, בלי DB)."""
import json
import threading
from pathlib import Path
from logger_setup import logger

DATA_DIR = Path('data')
SEARCH_MODES_FILE = DATA_DIR / 'search_modes.json'

_lock = threading.Lock()


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
