from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.error import NetworkError, TimedOut
from logger_setup import logger
from config import BOT_TOKEN, LOCAL_API_AVAILABLE, LOCAL_API_BASE_URL, LOCAL_API_FILE_URL
from bot_handlers import start, ask_format, button_click, handle_thank_you, version, mode
from utils import cleanup_temp_files, check_ffmpeg_on_startup

async def error_handler(update: Update, context):
    """טיפול בשגיאות של הבוט"""
    error = context.error
    try:
        if isinstance(error, (NetworkError, TimedOut)):
            # נסה שוב במקרה של בעיית רשת
            logger.warning(f"Network error occurred: {str(error)}")
            if update and update.message:
                await update.message.reply_text(
                    "חלה בעיית תקשורת, אנא נסה שוב 🔄"
                )
        elif any(msg in str(error) for msg in ["Sign in to confirm your age", "This video may be inappropriate for some users"]):
            logger.warning(f"Restricted content error: {str(error)}")
            if update and update.message:
                await update.message.reply_text(
                    "הסרטון מוגבל לצפייה, לא ניתן להוריד ⛔"
                )
        else:
            # שגיאות אחרות
            logger.error(f"Error occurred: {str(error)}")
            if update and update.message:
                await update.message.reply_text(
                    "אופס! משהו השתבש, אנא נסה שוב 😕"
                )
    except Exception as e:
        logger.error(f"Error in error handler: {str(e)}")

def main():
    try:
        # ניקוי קבצים זמניים מהפעלה קודמת
        cleanup_temp_files()
        
        # בדיקת FFmpeg
        check_ffmpeg_on_startup()
        
        if LOCAL_API_AVAILABLE:
            logger.info("Local API Server detected - using 2GB mode")
            # מצב 2GB עם Local API Server
            application = (ApplicationBuilder()
                          .token(BOT_TOKEN)
                          .base_url(LOCAL_API_BASE_URL)
                          .base_file_url(LOCAL_API_FILE_URL)
                          .get_updates_pool_timeout(30)
                          .get_updates_connection_pool_size(1)
                          .get_updates_connect_timeout(60)
                          .get_updates_read_timeout(60)
                          .build())
        else:
            logger.info("Local API Server not available - using standard 50MB mode")
            # מצב רגיל 50MB
            application = (ApplicationBuilder()
                          .token(BOT_TOKEN)
                          .get_updates_pool_timeout(30)
                          .get_updates_connection_pool_size(1)
                          .get_updates_connect_timeout(60)
                          .get_updates_read_timeout(60)
                          .build())
        
        # Add handlers
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('version', version))
        application.add_handler(CommandHandler('mode', mode))
        # תפיסת כל סוגי ההודעות חוץ מפקודות
        application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, ask_format))
        application.add_handler(CallbackQueryHandler(button_click))
        
        # Add error handler
        application.add_error_handler(error_handler)
        
        # Start the bot
        logger.info("Starting bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")

if __name__ == '__main__':
    main()