from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.error import NetworkError, TimedOut
from logger_setup import logger
from config import BOT_TOKEN
from bot_handlers import start, ask_format, button_click, handle_thank_you, version
from utils import cleanup_temp_files

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
        
        # Initialize the bot with custom settings
        # For 2GB file support: uncomment the next 2 lines and run Local Bot API Server
        # For 50MB limit: comment out the next 2 lines to use standard Telegram API
        application = (ApplicationBuilder()
                      .token(BOT_TOKEN)
                      .base_url("http://localhost:8081/bot")        # Comment this for 50MB mode
                      .base_file_url("http://localhost:8081/file/bot")  # Comment this for 50MB mode
                      .get_updates_pool_timeout(30)
                      .get_updates_connection_pool_size(1)
                      .get_updates_connect_timeout(60)
                      .get_updates_read_timeout(60)
                      .build())
        
        # Add handlers
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('version', version))
        
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