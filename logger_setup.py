import logging
from datetime import datetime
from config import HISTORY_FILE

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Disable httpx logging
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

def log_download(username: str, url: str, download_type: str, filename: str):
    """Log download to text file"""
    try:
        logger.info(f"Logging download for user {username}")
        with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
            f.write(f"""
=== הורדה חדשה ===
תאריך: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
משתמש: {username}
קישור: {url}
סוג הורדה: {download_type}
שם קובץ: {filename}
==================

""")
        logger.info("Download logged successfully")
    except Exception as e:
        logger.error(f"Error logging download: {str(e)}") 