from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from logger_setup import logger
from config import YOUTUBE_QUALITY_LEVELS, DEFAULT_FORMAT, VERSION, CHANGELOG, MAX_FILE_SIZE
from download_manager import download_with_quality
from utils import fetch_youtube_quality_options
import asyncio
import random
import re

THANK_YOU_RESPONSES = [
    "בכיף! 😊",
    "שמח לעזור! 🌟",
    "אין בעד מה! 💫",
    "תהנה/י! 🎵",
    "לשירותך! 🤖",
    "בשמחה! ✨"
]

SUPPORTED_SITES_MESSAGE = (
    "אני תומך בהורדה מיוטיוב, טוויטר, טיקטוק, אינסטגרם, פייסבוק, "
    "לינקדאין, פינטרסט, רדיט, וימאו, ואולי גם מעוד אתרי וידאו מוכרים, שווה לנסות 😊"
)

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
        f'{SUPPORTED_SITES_MESSAGE}\n'
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
        context.user_data.pop('youtube_quality_options', None)
        context.user_data.pop('current_quality_index', None)
        
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
        await message.reply_text('מה תרצה להוריד?', reply_markup=reply_markup)
    elif not is_thank:
        # אם אין URL וגם אין תודה, שולח הודעת הסבר
        await message.reply_text(
            "אנא שלח קישור תקין (URL).\n"
            f"{SUPPORTED_SITES_MESSAGE}"
        )

def build_quality_keyboard(quality_options):
    """בונה מקלדת בחירת איכות."""
    keyboard = []

    for i, quality in enumerate(quality_options):
        keyboard.append([
            InlineKeyboardButton(
                quality['quality_name'],
                callback_data=f'quality_{i}'
            )
        ])

    return InlineKeyboardMarkup(keyboard)


async def ask_quality(message, context, url):
    """שואל את המשתמש באיזו רזולוציה הוא רוצה להוריד."""
    quality_options = []

    try:
        await message.edit_text('בודק אילו איכויות זמינות לסרטון... ⏳')
        quality_options = await asyncio.to_thread(fetch_youtube_quality_options, url)
    except Exception as e:
        logger.warning(f"Could not fetch dynamic YouTube qualities: {e}")

    if not quality_options:
        quality_options = YOUTUBE_QUALITY_LEVELS
        prompt = 'לא הצלחתי לזהות רזולוציות זמינות, אז מציג אפשרויות כלליות.\nבאיזו איכות להוריד את הוידאו?'
    else:
        prompt = 'באיזו רזולוציה להוריד את הוידאו?'

    context.user_data['youtube_quality_options'] = quality_options
    reply_markup = build_quality_keyboard(quality_options)
    await message.edit_text(prompt, reply_markup=reply_markup)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('quality_'):
        # טיפול בבחירת איכות
        quality_index = int(query.data.split('_')[1])
        url = context.user_data.get('current_url')
        download_mode = context.user_data.get('download_mode')
        quality_options = context.user_data.get('youtube_quality_options') or YOUTUBE_QUALITY_LEVELS
        
        if not url or not download_mode:
            await query.message.reply_text('משהו השתבש, אנא שלח את הקישור שוב.')
            return

        if quality_index >= len(quality_options):
            await query.message.reply_text('בחירת האיכות כבר לא תקפה. שלח את הקישור שוב.')
            return
        
        context.user_data['current_quality_index'] = quality_index
        status_message = await query.message.edit_text('מתחיל בהורדה... ⏳')
        
        await download_with_quality(
            context,
            status_message,
            url,
            download_mode,
            quality_options[quality_index],
            quality_options
        )
    else:
        # טיפול בבחירת פורמט (אודיו/וידאו)
        download_mode = query.data  # 'audio' or 'video'
        context.user_data['download_mode'] = download_mode
        
        is_youtube = context.user_data.get('is_youtube', False)
        
        if download_mode == 'audio' or not is_youtube:
            # עבור אודיו או לא-יוטיוב - מתחילים הורדה מיד באיכות הטובה ביותר
            status_message = await query.message.edit_text('מתחיל בהורדה... ⏳')
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
            await ask_quality(query.message, context, context.user_data.get('current_url'))

async def handle_thank_you(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מטפל בהודעות תודה"""
    response = random.choice(THANK_YOU_RESPONSES)
    await update.message.reply_text(response) 

async def version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """הצגת מידע על הגרסה הנוכחית"""
    await update.message.reply_text(f"{CHANGELOG}")


async def mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """הצגת מידע על המצב הנוכחי של הבוט"""
    file_size_gb = MAX_FILE_SIZE / (1024 * 1024 * 1024)
    file_size_mb = MAX_FILE_SIZE / (1024 * 1024)
    
    if file_size_gb >= 1:
        mode_text = f"🚀 **מצב מתקדם** - מגבלת קבצים: {file_size_gb:.1f}GB"
        server_text = "✅ Local API Server זמין"
    else:
        mode_text = f"📱 **מצב פשוט** - מגבלת קבצים: {file_size_mb:.0f}MB"
        server_text = "❌ Local API Server לא זמין"
    
    message = f"""🤖 **מצב הבוט הנוכחי:**

{mode_text}
{server_text}

ℹ️ **הסבר מצבים:**
• **מצב פשוט (50MB)**: תמיד עובד עם Telegram API הרגיל
• **מצב חכם (2GB/50MB)**: מנסה Local Server, אם נכשל עובר ל-50MB

💡 **אפשרויות הפעלה:**
• `run_bot_simple_50MB` - תמיד 50MB
• `run_bot_advanced_2GB` - חכם עם auto-fallback"""
    
    await update.message.reply_text(message, parse_mode='Markdown') 