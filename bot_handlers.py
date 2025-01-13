from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from logger_setup import logger
from config import YOUTUBE_QUALITY_LEVELS, DEFAULT_FORMAT, VERSION, CHANGELOG
from download_manager import download_with_quality
import random
import re
import asyncio

THANK_YOU_RESPONSES = [
    "בכיף! 😊",
    "שמח לעזור! 🌟",
    "אין בעד מה! 💫",
    "תהנה/י! 🎵",
    "לשירותך! 🤖",
    "בשמחה! ✨"
]

def is_valid_url(url: str) -> bool:
    """בודק האם המחרוזת היא URL תקין"""
    url_pattern = re.compile(
        r'https?://'  # http:// או https://
        r'(?:(?:[\w-]+\.)+[\w-]+)'  # דומיין
        r'(?:/[^\s]*)?'  # נתיב אופציונלי
    )
    return bool(url_pattern.match(url))

def is_preferred_platform(url: str) -> bool:
    """בודק האם ה-URL הוא מאחת הפלטפורמות המועדפות"""
    preferred_platforms = re.compile(
        r'https?://(?:www\.)?'
        r'(?:youtube\.com/|youtu\.be/|'
        r'facebook\.com/|fb\.watch/|'
        r'instagram\.com/|'
        r'twitter\.com/|x\.com/|'
        r'tiktok\.com/)'
        r'[^\s]+'
    )
    return bool(preferred_platforms.match(url))

def is_thank_you_message(text: str) -> bool:
    """בודק האם ההודעה היא הודעת תודה"""
    thank_you_patterns = [
        '.*תודה.*',
        'תנקס',
        'thanks',
        'thank you',
        'thx'
    ]
    return any(re.search(pattern, text.lower()) for pattern in thank_you_patterns)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'שלום! 👋\n'
        'אני בוט להורדת סרטונים ממגוון אתרים כמו יוטיוב, פייסבוק, אינסטגרם, טיקטוק ועוד.\n'
        'פשוט שלח לי קישור ואני אשאל אותך אם תרצה להוריד אודיו או וידאו.\n'
        'עבור סרטוני יוטיוב תוכל גם לבחור איכות.'
    )

async def ask_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # בדיקת סוג ההודעה וטיפול בהתאם
    message = update.message
    
    # אם זו הודעת טקסט רגילה
    if message.text:
        text = message.text
    # אם זו הודעת מדיה עם כיתוב
    elif any([
        message.photo,
        message.video,
        message.audio,
        message.voice,
        message.document,
        message.sticker
    ]):
        text = message.caption or ""
    else:
        text = ""
    
    # בדיקות מקדימות
    is_thank = is_thank_you_message(text) if text else False
    words = text.split() if text else []
    valid_urls = [word for word in words if is_valid_url(word)]
    
    # מבצע את הפעולות הנדרשות
    if is_thank:
        # שולח תודה
        await handle_thank_you(update, context)
    
    if valid_urls:
        # מתייחס לקישור הראשון שנמצא
        url = valid_urls[0]
        context.user_data['current_url'] = url
        context.user_data['download_state'] = 'choosing_format'  # מעקב אחרי המצב
        
        # בדיקה האם זה קישור יוטיוב
        is_youtube = 'youtube.com' in url or 'youtu.be' in url
        context.user_data['is_youtube'] = is_youtube
        
        # אם יש יותר מקישור אחד, שולח הודעת הבהרה
        if len(valid_urls) > 1:
            await message.reply_text(
                "זיהיתי מספר קישורים בהודעה שלך. אני אוריד את התוכן מהקישור הראשון.\n"
                "אם תרצה להוריד גם מהקישורים הנוספים, אנא שלח כל קישור בהודעה נפרדת 😊"
            )
        
        keyboard = [
            [
                InlineKeyboardButton("אודיו 🎵", callback_data='audio'),
                InlineKeyboardButton("וידאו 🎥", callback_data='video')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        # שמירת ההודעה בקונטקסט
        context.user_data['last_bot_message'] = await message.reply_text('מה תרצה להוריד?', reply_markup=reply_markup)
    elif not is_thank:
        # אם אין URL וגם אין תודה, שולח הודעת הסבר
        await message.reply_text(
            "אנא שלח קישור תקין (URL) מאחד מהאתרים הבאים:\n"
            "• יוטיוב\n"
            "• פייסבוק\n"
            "• אינסטגרם\n"
            "• טוויטר/X\n"
            "• טיקטוק\n\n"
            "ניתן לנסות גם קישורים מאתרי מדיה פופולריים אחרים 😊"
        )

async def ask_quality(message, download_mode, context):
    """שואל את המשתמש באיזו איכות הוא רוצה להוריד"""
    keyboard = []
    
    for i, quality in enumerate(YOUTUBE_QUALITY_LEVELS):
        keyboard.append([
            InlineKeyboardButton(
                quality['quality_name'],
                callback_data=f'quality_{i}'
            )
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    # שמירת ההודעה בקונטקסט
    context.user_data['last_bot_message'] = await message.edit_text('באיזו איכות להוריד את הוידאו?', reply_markup=reply_markup)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('quality_'):
        # טיפול בבחירת איכות
        quality_index = int(query.data.split('_')[1])
        url = context.user_data.get('current_url')
        download_mode = context.user_data.get('download_mode')
        
        if not url or not download_mode:
            await query.message.reply_text('משהו השתבש, אנא שלח את הקישור שוב.')
            return
        
        context.user_data['current_quality_index'] = quality_index
        context.user_data['download_state'] = 'downloading'
        status_message = await query.message.edit_text('מתחיל בהורדה... ⏳')
        context.user_data['current_status_message'] = status_message  # שמירת הודעת הסטטוס
        
        await download_with_quality(
            context,
            status_message,
            url,
            download_mode,
            YOUTUBE_QUALITY_LEVELS[quality_index],
            YOUTUBE_QUALITY_LEVELS
        )
    else:
        # טיפול בבחירת פורמט (אודיו/וידאו)
        download_mode = query.data  # 'audio' or 'video'
        context.user_data['download_mode'] = download_mode
        
        is_youtube = context.user_data.get('is_youtube', False)
        
        if download_mode == 'audio' or not is_youtube:
            # עבור אודיו או לא-יוטיוב - מתחילים הורדה מיד באיכות הטובה ביותר
            context.user_data['download_state'] = 'downloading'
            status_message = await query.message.edit_text('מתחיל בהורדה... ⏳')
            context.user_data['current_status_message'] = status_message  # שמירת הודעת הסטטוס
            quality = DEFAULT_FORMAT if not is_youtube else YOUTUBE_QUALITY_LEVELS[1]
            await download_with_quality(
                context,
                status_message,
                context.user_data.get('current_url'),
                download_mode,
                quality,
                YOUTUBE_QUALITY_LEVELS if is_youtube else None
            )
        else:
            # עבור וידאו מיוטיוב - שואלים על איכות
            context.user_data['download_state'] = 'choosing_quality'
            await ask_quality(query.message, download_mode, context)

async def handle_thank_you(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מטפל בהודעות תודה"""
    response = random.choice(THANK_YOU_RESPONSES)
    await update.message.reply_text(response) 

async def version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """הצגת מידע על הגרסה הנוכחית"""
    await update.message.reply_text(f"{CHANGELOG}") 

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מבטל את ההורדה הנוכחית"""
    try:
        # בדיקת המצב הנוכחי
        current_state = context.user_data.get('download_state')
        
        if current_state in ['choosing_format', 'choosing_quality']:
            # מחיקת ההודעה האחרונה עם הכפתורים
            last_bot_message = context.user_data.get('last_bot_message')
            if last_bot_message:
                try:
                    await last_bot_message.delete()
                except Exception as e:
                    logger.error(f"Error deleting message: {e}")
            
            # מנקה את המצב ומודיע למשתמש
            context.user_data.clear()
            await update.message.reply_text('הפעולה בוטלה 🚫')
            return
            
        active_task = context.user_data.get('active_download_task')
        if active_task and not active_task.done():
            active_task.cancel()
            # מחיקת הודעת ההורדה הנוכחית
            current_status_message = context.user_data.get('current_status_message')
            if current_status_message:
                try:
                    await current_status_message.delete()
                except Exception as e:
                    logger.error(f"Error deleting status message: {e}")
            
            await update.message.reply_text('ההורדה בוטלה 🚫')
            return
            
        await update.message.reply_text('אין הורדה פעילה לביטול 🤔')
    except Exception as e:
        logger.error(f"Error in cancel command: {e}")
        await update.message.reply_text('משהו השתבש בניסיון לבטל את ההורדה 😕')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """הצגת הוראות שימוש"""
    await update.message.reply_text(
        'איך להשתמש בבוט:\n'
        '1. שלח קישור לסרטון\n'
        '2. בחר אם להוריד אודיו או וידאו\n'
        '3. אם זה סרטון יוטיוב, בחר איכות\n\n'
        'פקודות זמינות:\n'
        '/start - התחלה\n'
        '/help - עזרה\n'
        '/version - מידע על הגרסה\n'
        '/cancel - ביטול הורדה נוכחית'
    )

def register_handlers(application):
    """רישום כל ה-handlers של הבוט"""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("version", version))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_format))
    application.add_handler(CallbackQueryHandler(button_click))

    # לוגינג לבדיקה
    logger.info("Handlers registered successfully") 