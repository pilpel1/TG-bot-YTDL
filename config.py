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

# Download settings - will be set dynamically in bot.py
MAX_FILE_SIZE = 50 * 1024 * 1024  # Default: 50MB - will be updated if Local API Server is available

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
VERSION = "0.5.1"
CHANGELOG = """🆕 גרסה 0.5.1:
🔧 תיקון בעיות YouTube ושיפורי יציבות
• זיהוי אוטומטי של Local API Server (2GB vs 50MB)
• עדכון yt-dlp לגרסה האחרונה לתיקון בעיות nsig
• תיקון טעינת credentials מ-.env בצורה בטוחה
• שיפור טיפול בשגיאות YouTube והורדות כושלות""" 