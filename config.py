import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("Please set BOT_TOKEN in .env file")

# Paths
DOWNLOADS_DIR = Path('downloads')
LOGS_DIR = Path('logs')

# Create necessary directories
DOWNLOADS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Download settings - choose based on your setup:
# MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB - for standard Telegram Bot API
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB - for Local Bot API Server mode

# Quality levels for YouTube videos
YOUTUBE_QUALITY_LEVELS = [
    {
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]',
        'quality_name': 'איכות גבוהה'
    },
    {
        'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]',
        'quality_name': 'איכות רגילה'
    },
    {
        'format': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]',
        'quality_name': 'איכות נמוכה'
    }
]

# Default format for other platforms
DEFAULT_FORMAT = {
    'format': 'best',
    'quality_name': 'איכות מקסימלית'
}

# Version info
VERSION = "0.5.0"
CHANGELOG = """🆕 גרסה 0.5.0:
🚀 תמיכה בקבצים גדולים עד 2GB! (דרך Local Bot API Server)
• אפשרות לשליחת קבצים גדולים עד 2GB במקום 50MB
• הוראות התקנה לשני מצבים: פשוט (50MB) ומתקדם (2GB)
• תמיכה מלאה ב-WSL2 ו-Docker לשרת מקומי
• שיפור הוראות ההתקנה והתיעוד""" 