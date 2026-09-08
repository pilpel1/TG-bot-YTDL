from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.error import NetworkError, TimedOut
from logger_setup import logger
from config import BOT_TOKEN, LOCAL_API_AVAILABLE, LOCAL_API_BASE_URL, LOCAL_API_FILE_URL
from bot_handlers import (
    start, ask_format, button_click, handle_thank_you, version, help_command, mode,
    stop_download, search_mode, channels_command, broadcast_command, users_command,
    remember_incoming, build_bot_commands,
    refresh_all_user_command_menus,
)
from utils import cleanup_temp_files, check_ffmpeg_on_startup
from download_queue import DownloadQueue
from ytdlp_updater import YtdlpUpdateManager
from channel_watch import ChannelWatchManager


async def post_init(application):
    """מריץ אחרי שה-Application מאותחל אבל עדיין לפני תחילת ה-polling -
    הנקודה הנכונה להתחיל טאסקים ברקע (כמו worker התור), כי כאן כבר יש
    event loop רץ."""
    download_queue = DownloadQueue()
    download_queue.start()
    application.bot_data['download_queue'] = download_queue
    logger.info("Download queue initialized")

    ytdlp_updater = YtdlpUpdateManager(application)
    ytdlp_updater.start()
    application.bot_data['ytdlp_updater'] = ytdlp_updater

    channel_watch = ChannelWatchManager(application)
    channel_watch.start()
    application.bot_data['channel_watch'] = channel_watch

    # ברירת מחדל גלובלית (כבוי). לכל משתמש מתעדכן תפריט פרטי
    # ב-/search_mode, /start ו-/help דרך BotCommandScopeChat.
    await application.bot.set_my_commands(build_bot_commands(search_mode_on=False))
    await refresh_all_user_command_menus(application.bot)
    logger.info("Bot commands menu registered")

async def post_stop(application):
    """מריץ אחרי Application.stop() אבל עדיין עם event loop רץ - הנקודה
    הנכונה לעצור טאסקים ברקע שהתחלנו ב-post_init. בלי זה, worker התור
    נשאר "תלוי" כש-run_polling סוגר את ה-loop בסגירה עם Ctrl+C, וגורם
    ל-'Task was destroyed but it is pending!' בלוגים."""
    ytdlp_updater = application.bot_data.get('ytdlp_updater')
    if ytdlp_updater:
        await ytdlp_updater.stop()
        logger.info("yt-dlp updater stopped")

    channel_watch = application.bot_data.get('channel_watch')
    if channel_watch:
        await channel_watch.stop()
        logger.info("Channel watch stopped")

    download_queue = application.bot_data.get('download_queue')
    if download_queue:
        await download_queue.stop()
        logger.info("Download queue worker stopped")

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
                          .post_init(post_init)
                          .post_stop(post_stop)
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
                          .post_init(post_init)
                          .post_stop(post_stop)
                          .build())
        
        # group=-1 רץ בנוסף ל-group 0: רושם ID+שם בלי לבלוע הודעות/פקודות
        application.add_handler(MessageHandler(filters.ALL, remember_incoming), group=-1)
        application.add_handler(CallbackQueryHandler(remember_incoming), group=-1)
        # Add handlers
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CommandHandler('version', version))
        application.add_handler(CommandHandler('mode', mode))  # ניטור פנימי — לא בתפריט
        application.add_handler(CommandHandler('stop', stop_download))
        application.add_handler(CommandHandler('search_mode', search_mode))
        application.add_handler(CommandHandler('channels', channels_command))
        application.add_handler(CommandHandler('broadcast', broadcast_command))
        application.add_handler(CommandHandler('users', users_command))
        # תפיסת כל סוגי ההודעות חוץ מפקודות
        application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, ask_format))
        application.add_handler(CallbackQueryHandler(button_click))
        
        # Add error handler
        application.add_error_handler(error_handler)
        
        # Start the bot
        logger.info("Starting bot...")
        # False במפורש: הודעות שנשלחו בזמן שהתהליך היה כבוי לא נזרקות.
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
        )
        
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")

if __name__ == '__main__':
    main()