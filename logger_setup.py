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