import os
import re
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp
from pathlib import Path
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Disable httpx logging
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Get bot token from environment variable
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    logger.error("No bot token found in .env file!")
    raise ValueError("Please set BOT_TOKEN in .env file")

logger.info("Bot token loaded successfully")

# Initialize download history file
HISTORY_FILE = Path('logs') / 'download_history.txt'

# Create logs directory
Path('logs').mkdir(exist_ok=True)

# Create history file if it doesn't exist
if not HISTORY_FILE.exists():
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        f.write("=== היסטוריית הורדות ===\n\n")

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

def sanitize_filename(filename):
    """Clean filename from special characters"""
    # Replace Hebrew characters and other special characters with English transliteration
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    return filename

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'שלום! 👋\n'
        'אני בוט להורדת סרטונים מיוטיוב.\n'
        'פשוט שלח לי לינק ליוטיוב ואני אשאל אותך אם תרצה להוריד אודיו או וידאו.'
    )

async def ask_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if not 'youtube.com' in url and not 'youtu.be' in url:
        await update.message.reply_text('אנא שלח קישור תקין ליוטיוב')
        return
        
    context.user_data['current_url'] = url
    
    keyboard = [
        [
            InlineKeyboardButton("אודיו 🎵", callback_data='audio'),
            InlineKeyboardButton("וידאו 🎥", callback_data='video')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('מה תרצה להוריד?', reply_markup=reply_markup)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    download_mode = query.data  # 'audio' or 'video'
    url = context.user_data.get('current_url')
    username = query.from_user.username or query.from_user.first_name
    
    logger.info(f"Starting download process for URL: {url} in mode: {download_mode}")
    
    if not url:
        await query.message.reply_text('משהו השתבש, אנא שלח את הקישור שוב.')
        return
    
    status_message = await query.message.reply_text('מתחיל בהורדה... ⏳')
    
    try:
        # Create downloads directory if it doesn't exist
        downloads_dir = Path('downloads')
        downloads_dir.mkdir(exist_ok=True)
        
        base_opts = {
            'outtmpl': str(downloads_dir / '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'retries': 10,
            'fragment_retries': 10,
            'retry_sleep': lambda n: 5,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            }
        }
        
        if download_mode == 'audio':
            ydl_opts = {
                **base_opts,
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
        else:
            ydl_opts = {
                **base_opts,
                'format': 'best[ext=mp4]/best',
            }

        logger.info("Starting download with yt-dlp...")
        await status_message.edit_text('מוריד את הסרטון... 📥')
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                logger.info("Extracting video info...")
                info = ydl.extract_info(url, download=True)
                if info is None:
                    raise Exception("Failed to extract video info")
                
                logger.info("Preparing filename...")
                filename = Path(ydl.prepare_filename(info))
                
                if download_mode == 'audio':
                    old_filename = filename
                    filename = filename.with_suffix('.mp3')
                    logger.info(f"Converting {old_filename} to {filename}")
                
                # Check if file exists
                if not filename.exists():
                    raise FileNotFoundError(f"Downloaded file not found: {filename}")
                
                logger.info(f"File exists at: {filename}")
                await status_message.edit_text('שולח את הקובץ... 📤')
                
                # Log the download
                log_download(username, url, download_mode, filename.name)
                
                # Send the file
                with open(filename, 'rb') as f:
                    await query.message.reply_document(
                        document=f,
                        caption='הנה הקובץ שלך! 🎉'
                    )
                
                logger.info("Cleaning up...")
                # Clean up
                filename.unlink()  # Delete the file
                logger.info("Download process completed successfully")
                await status_message.delete()
                
            except Exception as e:
                logger.warning(f"First attempt failed: {str(e)}")
                await status_message.edit_text('מנסה שוב עם הגדרות אחרות... 🔄')
                
                # Modify options for second attempt
                if download_mode == 'video':
                    ydl_opts['format'] = 'best'
                else:
                    ydl_opts['format'] = 'worstaudio/worst'
                
                info = ydl.extract_info(url, download=True)
                if info is None:
                    raise Exception("Failed to download with alternative settings")
                
                filename = Path(ydl.prepare_filename(info))
                if download_mode == 'audio':
                    filename = filename.with_suffix('.mp3')
                
                if not filename.exists():
                    raise FileNotFoundError(f"Downloaded file not found after retry: {filename}")
                
                # Send the file
                with open(filename, 'rb') as f:
                    await query.message.reply_document(
                        document=f,
                        caption='הנה הקובץ שלך! 🎉'
                    )
                
                filename.unlink()  # Clean up
                await status_message.delete()
            
    except Exception as e:
        logger.error(f"Error downloading video: {str(e)}", exc_info=True)
        error_msg = str(e)
        if "Got error: " in error_msg:
            error_msg = "בעיית חיבור בהורדה. אנא נסה שוב."
        elif "No such file or directory" in error_msg:
            error_msg = "בעיה בשמירת הקובץ. אנא נסה שוב."
        await status_message.edit_text(f'אופס! משהו השתבש: {error_msg}')

def main():
    try:
        # Create downloads directory if it doesn't exist
        os.makedirs('downloads', exist_ok=True)
        
        # Initialize the bot
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler('start', start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_format))
        application.add_handler(CallbackQueryHandler(button_click))
        
        # Start the bot
        logger.info("Starting bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")

if __name__ == '__main__':
    main()