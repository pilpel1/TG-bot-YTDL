from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from logger_setup import logger
from config import YOUTUBE_QUALITY_LEVELS, DEFAULT_FORMAT, VERSION, CHANGELOG, MAX_FILE_SIZE
from download_manager import download_with_quality
from utils import (
    fetch_youtube_download_options,
    build_youtube_audio_option,
    get_best_allowed_quality_name,
    fetch_youtube_basic_info,
    build_youtube_playlist_download_options,
)
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
VERSIONS_URL = "https://github.com/pilpel1/TG-bot-YTDL/blob/main/VERSIONS.md"


def clear_download_state(context):
    """מנקה את מצב ההורדה הנוכחי של המשתמש."""
    for key in [
        'current_url',
        'youtube_quality_options',
        'youtube_download_options',
        'youtube_prefetch_task',
        'youtube_prefetch_url',
        'youtube_prefetch_waiting_for_choice',
        'current_quality_index',
        'download_mode',
        'is_youtube',
    ]:
        context.user_data.pop(key, None)

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
        context.user_data.pop('youtube_download_options', None)
        context.user_data.pop('youtube_prefetch_task', None)
        context.user_data.pop('youtube_prefetch_url', None)
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
        
        if is_youtube:
            status_message = await message.reply_text(
                'מה תרצה להוריד?\n'
                'אפשר לבחור כבר עכשיו. בינתיים בודק איכויות וידאו זמינות ברקע... ⏳',
                reply_markup=build_format_keyboard()
            )
            prefetch_task = start_youtube_download_options_prefetch(context, url)
            prefetch_task.add_done_callback(
                lambda completed_task: asyncio.create_task(
                    notify_youtube_prefetch_ready(context, url, status_message, completed_task)
                )
            )
        else:
            await message.reply_text('מה תרצה להוריד?', reply_markup=build_format_keyboard())
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
                quality.get('button_text', quality['quality_name']),
                callback_data=f'quality_{i}'
            )
        ])

    keyboard.append([
        InlineKeyboardButton("ביטול", callback_data='cancel')
    ])

    return InlineKeyboardMarkup(keyboard)


def build_format_keyboard():
    """בונה מקלדת בחירה בסיסית של אודיו/וידאו."""
    keyboard = [
        [
            InlineKeyboardButton("אודיו 🎵", callback_data='audio'),
            InlineKeyboardButton("וידאו 🎥", callback_data='video')
        ],
        [
            InlineKeyboardButton("ביטול", callback_data='cancel')
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_fallback_youtube_download_options():
    """אפשרויות fallback כלליות אם חילוץ ה-metadata נכשל."""
    fallback_options = [quality.copy() for quality in YOUTUBE_QUALITY_LEVELS]
    fallback_options.append(build_youtube_audio_option())
    return fallback_options


def build_playlist_prompt(playlist_info):
    """בונה הודעת בחירה לפלייליסט יוטיוב."""
    title = (playlist_info or {}).get('title') or 'הפלייליסט'
    entries = (playlist_info or {}).get('entries') or []
    total_videos = len([entry for entry in entries if entry is not None])

    return (
        f'זיהיתי פלייליסט: {title}\n'
        f'מספר סרטונים: {total_videos}\n\n'
        'ההגדרה שתיבחר תחול אוטומטית על כל הסרטונים בפלייליסט.\n'
        'גודל הקובץ ייבדק מאחורי הקלעים עבור כל סרטון, '
        'וסרטונים גדולים מדי או בעייתיים יידלגו.\n\n'
        'מה להוריד מהפלייליסט?'
    )


async def prefetch_youtube_download_options(url):
    """שולף ברקע metadata ואפשרויות הורדה ליוטיוב."""
    playlist_info = None

    try:
        playlist_info = await asyncio.to_thread(fetch_youtube_basic_info, url)
    except Exception as e:
        logger.warning(f"Could not fetch basic YouTube info: {e}")

    if playlist_info and 'entries' in playlist_info:
        return {
            'download_options': build_youtube_playlist_download_options(),
            'prompt': build_playlist_prompt(playlist_info)
        }

    download_options = []
    try:
        download_options = await asyncio.to_thread(
            fetch_youtube_download_options,
            url,
            MAX_FILE_SIZE
        )
    except Exception as e:
        logger.warning(f"Could not fetch dynamic YouTube download options: {e}")

    if not download_options:
        return {
            'download_options': build_fallback_youtube_download_options(),
            'prompt': 'לא הצלחתי לזהות את כל האיכויות הזמינות כרגע.\nבחר מה להוריד:'
        }

    return {
        'download_options': download_options,
        'prompt': 'בחר מה להוריד:'
    }


def start_youtube_download_options_prefetch(context, url):
    """מתחיל prefetch ברקע כדי לקצר את ההמתנה אחרי לחיצה על וידאו."""
    task = asyncio.create_task(prefetch_youtube_download_options(url))
    context.user_data['youtube_prefetch_task'] = task
    context.user_data['youtube_prefetch_url'] = url
    context.user_data['youtube_prefetch_waiting_for_choice'] = True
    return task


async def notify_youtube_prefetch_ready(context, url, message, task):
    """מעדכן את הודעת הבחירה כשה-prefetch מוכן, אם המשתמש עוד לא בחר."""
    try:
        await task
    except Exception as e:
        logger.warning(f"Could not finalize YouTube prefetch status message: {e}")
        return

    if context.user_data.get('youtube_prefetch_task') is not task:
        return

    if context.user_data.get('youtube_prefetch_url') != url:
        return

    if not context.user_data.get('youtube_prefetch_waiting_for_choice'):
        return

    try:
        await message.edit_text(
            'מה תרצה להוריד?\n'
            'אפשר לבחור כבר עכשיו. איכויות הווידאו זמינות.',
            reply_markup=build_format_keyboard()
        )
    except Exception as e:
        logger.warning(f"Could not update YouTube prefetch ready message: {e}")


async def get_youtube_download_options_result(context, url):
    """מחזיר את תוצאת ה-prefetch אם קיימת, או מבצע שליפה במקום."""
    task = context.user_data.get('youtube_prefetch_task')
    prefetched_url = context.user_data.get('youtube_prefetch_url')

    if task and prefetched_url == url:
        return await task

    return await prefetch_youtube_download_options(url)


async def show_youtube_download_options(message, context, url):
    """מציג את אפשרויות הווידאו ליוטיוב אחרי לחיצה על וידאו."""
    prefetch_task = context.user_data.get('youtube_prefetch_task')
    prefetched_url = context.user_data.get('youtube_prefetch_url')
    context.user_data['youtube_prefetch_waiting_for_choice'] = False

    if prefetch_task and prefetched_url == url and not prefetch_task.done():
        await message.edit_text('בודק איכויות זמינות וגודל משוער... ⏳')

    prefetched_result = await get_youtube_download_options_result(context, url)
    download_options = prefetched_result['download_options']
    prompt = prefetched_result['prompt']

    context.user_data['youtube_download_options'] = download_options
    context.user_data.pop('youtube_prefetch_task', None)
    context.user_data.pop('youtube_prefetch_url', None)
    reply_markup = build_quality_keyboard(download_options)
    await message.edit_text(prompt, reply_markup=reply_markup)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.data == 'cancel':
        clear_download_state(context)
        await query.answer('בוטל')
        await query.message.edit_text('בוטל. אפשר לשלוח קישור חדש.')
        return
    
    if query.data.startswith('quality_'):
        # טיפול בבחירת איכות
        quality_index = int(query.data.split('_')[1])
        url = context.user_data.get('current_url')
        quality_options = context.user_data.get('youtube_download_options') or build_fallback_youtube_download_options()
        
        if not url:
            await query.message.reply_text('משהו השתבש, אנא שלח את הקישור שוב.')
            return

        if quality_index >= len(quality_options):
            await query.message.reply_text('בחירת האיכות כבר לא תקפה. שלח את הקישור שוב.')
            return

        selected_option = quality_options[quality_index]
        download_mode = selected_option.get('download_mode') or context.user_data.get('download_mode')

        if selected_option.get('is_blocked'):
            best_allowed_quality_name = get_best_allowed_quality_name(quality_options) or 'לא ידוע'
            await query.answer(
                'הקובץ גדול מדי ולא יכול להישלח.\n'
                f'כדאי לנסות איכות נמוכה יותר. האיכות הגבוהה ביותר שזמינה: {best_allowed_quality_name}',
                show_alert=True
            )
            return
        
        await query.answer()
        context.user_data['current_quality_index'] = quality_index
        status_message = await query.message.edit_text('מתחיל בהורדה... ⏳')
        
        await download_with_quality(
            context,
            status_message,
            url,
            download_mode,
            selected_option,
            quality_options
        )
    else:
        # טיפול בבחירת פורמט (אודיו/וידאו)
        context.user_data['youtube_prefetch_waiting_for_choice'] = False
        await query.answer()
        download_mode = query.data  # 'audio' or 'video'
        context.user_data['download_mode'] = download_mode
        
        is_youtube = context.user_data.get('is_youtube', False)
        
        if download_mode == 'audio':
            context.user_data.pop('youtube_prefetch_task', None)
            context.user_data.pop('youtube_prefetch_url', None)
            status_message = await query.message.edit_text('מתחיל בהורדה... ⏳')
            quality = build_youtube_audio_option() if is_youtube else DEFAULT_FORMAT
            await download_with_quality(
                context,
                status_message,
                context.user_data.get('current_url'),
                download_mode,
                quality,
                context.user_data.get('youtube_download_options') if is_youtube else None
            )
        elif not is_youtube:
            # עבור פלטפורמות שאינן יוטיוב - מתחילים הורדה מיד באיכות הטובה ביותר
            status_message = await query.message.edit_text('מתחיל בהורדה... ⏳')
            quality = DEFAULT_FORMAT
            await download_with_quality(
                context,
                status_message,
                context.user_data.get('current_url'),
                download_mode,
                quality,
                None
            )
        else:
            await show_youtube_download_options(
                query.message,
                context,
                context.user_data.get('current_url')
            )

async def handle_thank_you(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מטפל בהודעות תודה"""
    response = random.choice(THANK_YOU_RESPONSES)
    await update.message.reply_text(response) 

async def version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """הצגת מידע על הגרסה הנוכחית"""
    await update.message.reply_text(
        f"{CHANGELOG}\n\n"
        f"📚 לגרסאות קודמות: <a href=\"{VERSIONS_URL}\">צפייה ב-GitHub</a>",
        parse_mode='HTML',
        disable_web_page_preview=True
    )


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