import logging
from datetime import datetime
import os
from config import LOGS_DIR

# Configure logging (stdout for systemd/journalctl + file for the logs/ folder)
_LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(
    format=_LOG_FORMAT,
    level=logging.INFO
)

_root_logger = logging.getLogger()
if not any(isinstance(handler, logging.FileHandler) for handler in _root_logger.handlers):
    _file_handler = logging.FileHandler(LOGS_DIR / 'bot.log', encoding='utf-8')
    _file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    _root_logger.addHandler(_file_handler)

# Disable httpx logging
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def format_requester_for_log(chat=None, chat_id=None) -> str:
    """תווית ללוגים: שם אם יש, ותמיד chat_id.

    לא לשימוש בשמות קבצי היסטוריה — רק journalctl/bot.log, כולל כישלונות.
    """
    def as_text(value):
        return value.strip() if isinstance(value, str) and value.strip() else ''

    def as_id(value):
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    resolved_id = as_id(chat_id)
    username = ''
    display_name = ''
    if chat is not None:
        resolved_id = as_id(getattr(chat, 'id', None)) or resolved_id
        username = as_text(getattr(chat, 'username', None)).lstrip('@')
        first = as_text(getattr(chat, 'first_name', None))
        last = as_text(getattr(chat, 'last_name', None))
        title = as_text(getattr(chat, 'title', None))
        display_name = ' '.join(part for part in (first, last) if part) or title

    if username and display_name:
        name = f'{display_name} (@{username})'
    elif username:
        name = f'@{username}'
    else:
        name = display_name

    if name and resolved_id is not None:
        return f'{name} (chat_id={resolved_id})'
    if resolved_id is not None:
        return f'chat_id={resolved_id}'
    return name or 'unknown'


def log_download(username: str, url: str, download_type: str, filename: str):
    """Log download to user-specific text file"""
    try:
        logger.info(f"Logging download for user {username}")
        # יצירת שם קובץ ייחודי למשתמש
        user_log_file = LOGS_DIR / f'{username}_history.txt'
        
        # יצירת קובץ אם לא קיים
        if not user_log_file.exists():
            with open(user_log_file, 'w', encoding='utf-8') as f:
                f.write(f"=== היסטוריית הורדות עבור {username} ===\n\n")
        
        with open(user_log_file, 'a', encoding='utf-8') as f:
            f.write(f"""
=== הורדה חדשה ===
תאריך: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
משתמש: {username}
קישור: {url}
סוג הורדה: {download_type}
שם קובץ: {filename}
==================

""")
        logger.info(f"Download logged successfully for user {username}")
    except Exception as e:
        logger.error(f"Error logging download for user {username}: {str(e)}") 