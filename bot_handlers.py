from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat
from telegram.ext import ContextTypes
from logger_setup import logger
from config import (
    YOUTUBE_QUALITY_LEVELS,
    DEFAULT_FORMAT,
    VERSION,
    CHANGELOG,
    MAX_FILE_SIZE,
    MAX_MIX_DOWNLOAD_LIMIT,
    YOUTUBE_SEARCH_RESULTS_LIMIT,
    YOUTUBE_SEARCH_MIN_QUERY_LENGTH,
    YOUTUBE_SEARCH_MAX_QUERY_LENGTH,
)
from download_manager import download_with_quality, download_playlist
from download_queue import CancellationToken
from utils import (
    fetch_youtube_download_options,
    build_youtube_audio_option,
    get_best_allowed_quality_name,
    fetch_youtube_basic_info,
    build_youtube_playlist_download_options,
    is_youtube_mix_url,
    is_youtube_playlist_url,
    count_playlist_entries,
    search_youtube,
    format_search_result_button_text,
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

# מגביל כמה entries נשלפים בזיהוי הראשוני של פלייליסט/מיקס.
# למיקס אין "סוף" אמיתי אז אין טעם לחלץ הכל. לפלייליסט רגיל זה לא פוגע
# בדיוק המספר הכולל - yt-dlp מחזיר playlist_count מדויק גם עם הגבלה כזו
# (מגיע ממטא-דטה של הדף הראשי, לא מספירת entries בפועל).
# 20 נותן שוליים מעל האופציה הכי גדולה בכפתורים (15) בלי לחכות לרשת יותר מדי.
PLAYLIST_METADATA_ENTRIES_CAP = 20


async def enqueue_download_job(context, status_message, coro_factory, weight=1, cancel_token=None):
    """מכניס ג'וב הורדה לתור הגלובלי ומחזיר מיד - לא מחכה לסיום ההורדה.
    כך ה-handler משתחרר ומאפשר לבוט להמשיך להגיב למשתמשים אחרים בזמן
    שההורדה עצמה רצה ברקע דרך worker התור.

    weight: מספר "יחידות עבודה" משוער בג'וב (1 לסרטון בודד, N לפלייליסט של
    N סרטונים) - רק לצורך הערכת זמן, לא משפיע על הסדר.

    cancel_token: אותו טוקן שכבר נסגר (closure) לתוך coro_factory כ-
    should_cancel - מועבר גם לתור כדי ש-/stop יוכל לסמן אותו דרך cancel()."""
    download_queue = context.bot_data['download_queue']
    return await download_queue.enqueue(
        chat_id=status_message.chat_id,
        status_message=status_message,
        coro_factory=coro_factory,
        weight=weight,
        cancel_token=cancel_token,
    )


async def stop_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /stop - מבטלת את ההורדה הפעילה/הממתינה בתור של המשתמש הזה, אם יש."""
    chat_id = update.effective_chat.id
    download_queue = context.bot_data.get('download_queue')
    if not download_queue:
        await update.message.reply_text('אין תור הורדות פעיל כרגע.')
        return

    cancelled_count = download_queue.cancel_all_for_chat(chat_id)
    if cancelled_count == 0:
        await update.message.reply_text('אין לך הורדה פעילה או ממתינה כרגע 🤷')
        return

    if cancelled_count == 1:
        await update.message.reply_text('ביטלתי את ההורדה 🛑')
    else:
        await update.message.reply_text(f'ביטלתי {cancelled_count} הורדות (כל מה שהיה לך בתור) 🛑')


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
        'pending_batch_quality',
        'pending_batch_quality_levels',
        'is_batch_mix',
        'batch_playlist_info',
        'youtube_search_results',
        'youtube_search_query',
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


def is_searchable_text(text: str) -> bool:
    """בודק אם הטקסט שווה ניסיון חיפוש יוטיוב (לא URL).

    לא כל טקסט שאינו URL נחשב חיפוש — רק מחרוזות באורך סביר שמכילות
    לפחות אות אחת. טקסט ארוך מדי, קצר מדי, או בלי אותיות → הודעת
    הסבר גנרית בלי לפנות ליוטיוב."""
    stripped = (text or '').strip()
    if len(stripped) < YOUTUBE_SEARCH_MIN_QUERY_LENGTH:
        return False
    if len(stripped) > YOUTUBE_SEARCH_MAX_QUERY_LENGTH:
        return False
    return bool(re.search(r'[a-zA-Z\u0590-\u05FF]', stripped))


def is_search_mode_enabled(context) -> bool:
    """מצב חיפוש כבוי כברירת מחדל - מופעל רק ב-/search_mode.

    נשמר ב-context.user_data → פר-משתמש (לא משפיע על משתמשים אחרים)."""
    return bool(context.user_data.get('search_mode'))


def build_bot_commands(search_mode_on: bool = False):
    """בונה רשימת פקודות לתפריט טלגרם, עם סטטוס מצב חיפוש בתיאור."""
    search_desc = (
        'מצב חיפוש (פעיל כעת)'
        if search_mode_on
        else 'מצב חיפוש (כבוי כעת)'
    )
    return [
        BotCommand('start', 'הודעת פתיחה'),
        BotCommand('help', 'עזרה, פקודות ומגבלת קבצים'),
        BotCommand('search_mode', search_desc),
        BotCommand('stop', 'ביטול הורדה פעילה או ממתינה'),
        BotCommand('version', 'גרסה נוכחית ושינויים'),
    ]


async def sync_user_command_menu(bot, chat_id, search_mode_on: bool):
    """מעדכן את תפריט הפקודות רק לצ'אט הזה (BotCommandScopeChat).

    ככה סטטוס 'פעיל/כבוי' של משתמש א' לא מופיע אצל משתמש ב'.
    נקרא גם ב-/start ו-/help כדי לתקן תיאור ישן אחרי ריסטארט בוט
    (user_data בזיכרון מתאפס, אבל תפריט טלגרם נשאר עד שמעדכנים)."""
    try:
        await bot.set_my_commands(
            build_bot_commands(search_mode_on),
            scope=BotCommandScopeChat(chat_id=chat_id),
        )
    except Exception as e:
        logger.warning(f"Could not sync command menu for chat {chat_id}: {e}")


def build_unrecognized_input_message(search_mode_on: bool = False) -> str:
    """הודעה לטקסט שלא זוהה כקישור (וכשמצב חיפוש כבוי - גם לא כתודה)."""
    if search_mode_on:
        return (
            "לא הצלחתי להבין את ההודעה.\n"
            "במצב חיפוש שלח שם שיר/אמן (או קישור להורדה).\n"
            "לכיבוי: /search_mode"
        )
    return (
        "אנא שלח קישור תקין (URL).\n"
        f"{SUPPORTED_SITES_MESSAGE}\n"
        "לחיפוש ביוטיוב לפי טקסט: /search_mode"
    )


def build_search_results_keyboard(results):
    """בונה מקלדת עם תוצאות חיפוש יוטיוב."""
    keyboard = [
        [InlineKeyboardButton(
            format_search_result_button_text(index, result),
            callback_data=f'search_pick_{index}'
        )]
        for index, result in enumerate(results)
    ]
    keyboard.append([InlineKeyboardButton("❌ ביטול", callback_data='cancel')])
    return InlineKeyboardMarkup(keyboard)


async def handle_youtube_text_search(message, context, query):
    """מחפש ביוטיוב ומציג תוצאות (כולל כפתור ביטול)."""
    status_message = await message.reply_text('מחפש ביוטיוב... 🔍', quote=True)
    try:
        results = await asyncio.to_thread(
            search_youtube,
            query,
            YOUTUBE_SEARCH_RESULTS_LIMIT,
        )
    except Exception as e:
        logger.error(f"YouTube search failed for query '{query}': {e}")
        await status_message.edit_text('החיפוש נכשל, נסה שוב 😕')
        return

    if not results:
        await status_message.edit_text(
            f'לא מצאתי תוצאות עבור "{query}" 😕\n'
            'נסה ניסוח אחר, או כבה מצב חיפוש עם /search_mode'
        )
        return

    context.user_data['youtube_search_results'] = results
    context.user_data['youtube_search_query'] = query
    await status_message.edit_text(
        f'תוצאות חיפוש עבור "{query}":\nבחר סרטון:',
        reply_markup=build_search_results_keyboard(results),
    )


async def search_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מפעיל/מכבה מצב חיפוש טקסט חופשי ביוטיוב (פר-משתמש ב-user_data)."""
    enabled = not is_search_mode_enabled(context)
    context.user_data['search_mode'] = enabled
    await sync_user_command_menu(
        context.bot,
        update.effective_chat.id,
        enabled,
    )
    if enabled:
        await update.message.reply_text(
            'מצב חיפוש הופעל 🔍\n'
            'שלח שם שיר, אמן או כל טקסט — אחפש ביוטיוב.\n'
            'אם יש קישור בהודעה, אתייחס רק אליו (הורדה).\n'
            'לכיבוי: /search_mode שוב'
        )
    else:
        await update.message.reply_text(
            'מצב חיפוש כובה.\n'
            'שלח קישור להורדה כרגיל.\n'
            'להפעלה מחדש: /search_mode'
        )


async def begin_youtube_download_flow(message, context, url, *, edit_existing=False):
    """מתחיל את זרימת הבחירה (אודיו/וידאו) לקישור יוטיוב."""
    context.user_data['current_url'] = url
    context.user_data['is_youtube'] = True
    context.user_data.pop('youtube_quality_options', None)
    context.user_data.pop('youtube_download_options', None)
    context.user_data.pop('youtube_prefetch_task', None)
    context.user_data.pop('youtube_prefetch_url', None)
    context.user_data.pop('current_quality_index', None)

    prompt = (
        'מה להוריד לך? נא לבחור\n'
        '(איכויות הווידאו נבדקות ברקע...)'
    )
    if edit_existing:
        status_message = await message.edit_text(
            prompt,
            reply_markup=build_format_keyboard(),
        )
    else:
        status_message = await message.reply_text(
            prompt,
            reply_markup=build_format_keyboard(),
            quote=True,
        )

    prefetch_task = start_youtube_download_options_prefetch(context, url)
    prefetch_task.add_done_callback(
        lambda completed_task: asyncio.create_task(
            notify_youtube_prefetch_ready(context, url, status_message, completed_task)
        )
    )
    return status_message

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await sync_user_command_menu(
        context.bot,
        update.effective_chat.id,
        is_search_mode_enabled(context),
    )
    await update.message.reply_text(
        'שלום! 👋\n'
        f'{SUPPORTED_SITES_MESSAGE}\n'
        'שלח קישור להורדה, או /search_mode לחיפוש ביוטיוב לפי טקסט.\n'
        'עזרה מלאה ופקודות: /help'
    )


def build_file_limit_summary() -> str:
    """שורת מצב מגבלת קבצים (מידע בלבד — המשתמש לא יכול לשנות זאת)."""
    file_size_gb = MAX_FILE_SIZE / (1024 * 1024 * 1024)
    file_size_mb = MAX_FILE_SIZE / (1024 * 1024)
    if file_size_gb >= 1:
        return f'מגבלת קבצים נוכחית: עד {file_size_gb:.1f}GB (Local API)'
    return f'מגבלת קבצים נוכחית: עד {file_size_mb:.0f}MB (Telegram רגיל)'


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """עזרה כללית: מה הבוט עושה, פקודות, ומגבלת קבצים."""
    search_mode_on = is_search_mode_enabled(context)
    await sync_user_command_menu(
        context.bot,
        update.effective_chat.id,
        search_mode_on,
    )
    search_status = 'דלוק 🔍' if search_mode_on else 'כבוי'
    await update.message.reply_text(
        '🤖 עזרה\n\n'
        f'{SUPPORTED_SITES_MESSAGE}\n\n'
        'איך משתמשים:\n'
        '• שלח קישור — אשאל אודיו/וידאו (וביוטיוב גם איכות)\n'
        '• חיפוש לפי שם שיר/אמן — הפעל /search_mode ואז שלח טקסט\n'
        '• אם יש קישור בהודעה, אתייחס רק אליו\n\n'
        'פקודות:\n'
        '/start — הודעת פתיחה\n'
        '/help — העזרה הזאת\n'
        '/search_mode — הפעלה/כיבוי חיפוש טקסט (כרגע: '
        f'{search_status})\n'
        '/stop — ביטול הורדה פעילה או ממתינה בתור\n'
        '/version — גרסה נוכחית ושינויים\n\n'
        f'{build_file_limit_summary()}'
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
    
    words = text.split() if text else []
    valid_urls = [word for word in words if is_valid_url(word)]
    search_mode_on = is_search_mode_enabled(context)

    # קישור תמיד מנצח — גם אם יש מסביב טקסט ארוך / "תודה" / מצב חיפוש דלוק
    if valid_urls:
        url = valid_urls[0]
        context.user_data.pop('youtube_search_results', None)
        context.user_data.pop('youtube_search_query', None)
        context.user_data['current_url'] = url
        context.user_data.pop('youtube_quality_options', None)
        context.user_data.pop('youtube_download_options', None)
        context.user_data.pop('youtube_prefetch_task', None)
        context.user_data.pop('youtube_prefetch_url', None)
        context.user_data.pop('current_quality_index', None)

        is_youtube = 'youtube.com' in url or 'youtu.be' in url
        context.user_data['is_youtube'] = is_youtube

        if len(valid_urls) > 1:
            await message.reply_text(
                "זיהיתי מספר קישורים בהודעה שלך. אני אוריד את התוכן מהקישור הראשון.\n"
                "אם תרצה להוריד גם מהקישורים הנוספים, אנא שלח כל קישור בהודעה נפרדת 😊",
                quote=True
            )

        if is_youtube:
            await begin_youtube_download_flow(message, context, url)
        else:
            await message.reply_text('מה תרצה להוריד?', reply_markup=build_format_keyboard(), quote=True)
        return

    # בלי קישור: מצב חיפוש → חיפוש (כולל "תודה עוזי חיטמן")
    if search_mode_on:
        if is_searchable_text(text):
            await handle_youtube_text_search(message, context, text.strip())
        else:
            await message.reply_text(build_unrecognized_input_message(search_mode_on=True))
        return

    # מצב רגיל (חיפוש כבוי): תודה כמו פעם, אחרת הודעת קישור
    if text and is_thank_you_message(text):
        await handle_thank_you(update, context)
        return

    await message.reply_text(build_unrecognized_input_message(search_mode_on=False))

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
        InlineKeyboardButton("❌ ביטול", callback_data='cancel')
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
            InlineKeyboardButton("❌ ביטול", callback_data='cancel')
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_batch_count_keyboard(entries_count=0, is_mix=True):
    """בונה מקלדת לבחירת כמות סרטונים להורדה מפלייליסט/מיקס יוטיוב.
    אם entries_count לא ידוע (0) - מציג ברירת מחדל של 5/10/15 בלי לחכות לרשת.

    מיקס נבנה דינמית ואינסופית ע"י יוטיוב - אין באמת "סוף" ידוע, ולכן אין
    כפתור "הכל"; יש תקרה קשיחה (MAX_MIX_DOWNLOAD_LIMIT) במקום.
    פלייליסט רגיל הוא סופי אמיתי, אז "הכל" הוא ערך מדויק וידוע ומוצג עם
    המספר (playlist_count)."""
    suggested = [count for count in (5, 10, 15) if entries_count == 0 or entries_count >= count]
    keyboard = []
    if suggested:
        keyboard.append([
            InlineKeyboardButton(f"{count} ראשונים", callback_data=f'batch_count_{count}')
            for count in suggested
        ])

    if is_mix:
        keyboard.append([
            InlineKeyboardButton(
                f'{MAX_MIX_DOWNLOAD_LIMIT} (מקסימום)',
                callback_data=f'batch_count_{MAX_MIX_DOWNLOAD_LIMIT}'
            )
        ])
    else:
        all_label = f'כל הפלייליסט ({entries_count})' if entries_count else 'כל הפלייליסט'
        keyboard.append([InlineKeyboardButton(all_label, callback_data='batch_count_all')])

    keyboard.append([InlineKeyboardButton("❌ ביטול", callback_data='cancel')])
    return InlineKeyboardMarkup(keyboard)


def build_fallback_youtube_download_options():
    """אפשרויות fallback כלליות אם חילוץ ה-metadata נכשל."""
    return [quality.copy() for quality in YOUTUBE_QUALITY_LEVELS]


def build_playlist_prompt(playlist_info, is_mix=False):
    """בונה הודעת בחירה לפלייליסט/מיקס יוטיוב.

    למיקס לא מציגים מספר סרטונים כאן - יוטיוב לא חושף מונה כולל למיקסים
    (הם נבנים דינמית), והמספר המתאים (מוגבל/משוער) מוצג בהמשך במסך
    "כמה להוריד" (maybe_prompt_batch_count).
    לפלייליסט רגיל יש playlist_count מדויק שמגיע ממטא-דטה בלי תלות
    בכמה entries בפועל נשלפו, אז אפשר להציג אותו כאן בביטחון."""
    title = (playlist_info or {}).get('title') or ('המיקס' if is_mix else 'הפלייליסט')

    if is_mix:
        return (
            f'זיהיתי מיקס יוטיוב: {title}\n\n'
            'ההגדרה שתיבחר תחול על הסרטונים שתבחר להוריד מהמיקס.\n'
            'גודל הקובץ ייבדק מאחורי הקלעים עבור כל סרטון, '
            'וסרטונים גדולים מדי או בעייתיים יידלגו.\n\n'
            'מה להוריד מהמיקס?'
        )

    total_videos = (playlist_info or {}).get('playlist_count')
    count_line = f'מספר סרטונים: {total_videos}\n\n' if total_videos else '\n'

    return (
        f'זיהיתי פלייליסט: {title}\n'
        f'{count_line}'
        'ההגדרה שתיבחר תחול על הסרטונים שתבחר להוריד מהפלייליסט.\n'
        'גודל הקובץ ייבדק מאחורי הקלעים עבור כל סרטון, '
        'וסרטונים גדולים מדי או בעייתיים יידלגו.\n\n'
        'מה להוריד מהפלייליסט?'
    )


async def prefetch_youtube_download_options(url):
    """שולף ברקע metadata ואפשרויות הורדה ליוטיוב."""
    playlist_info = None
    is_mix = is_youtube_mix_url(url)

    try:
        # מגביל תמיד ל-PLAYLIST_METADATA_ENTRIES_CAP - מהיר גם למיקסים גדולים
        # וגם לפלייליסטים גדולים, ולא פוגע בדיוק playlist_count לפלייליסט רגיל.
        playlist_info = await asyncio.to_thread(
            fetch_youtube_basic_info, url, PLAYLIST_METADATA_ENTRIES_CAP
        )
    except Exception as e:
        logger.warning(f"Could not fetch basic YouTube info: {e}")

    if playlist_info and 'entries' in playlist_info:
        total_count = playlist_info.get('playlist_count')
        capped_count = count_playlist_entries(playlist_info)
        return {
            'download_options': build_youtube_playlist_download_options(),
            'prompt': build_playlist_prompt(playlist_info, is_mix=is_mix),
            'is_mix': is_mix,
            'is_batch': True,
            'batch_entries_count': total_count if total_count else capped_count,
            'playlist_info': playlist_info,
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
            'מה להוריד לך? נא לבחור\n'
            '(איכויות הווידאו מוכנות לבחירה.)',
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


async def maybe_prompt_batch_count(message, context, url, selected_option, quality_levels):
    """אם ה-URL הוא פלייליסט או מיקס - שואל את המשתמש כמה סרטונים להוריד.
    מחזיר True אם נשאל, False אם זה בעצם לא פלייליסט/מיקס תקין (ואז ממשיכים
    בזרימה הרגילה של סרטון בודד).

    הזיהוי הראשוני "יש list= בקישור" הוא regex מיידי בלי רשת - כדי לא לפגוע
    בתגובתיות של הרוב המכריע (סרטונים רגילים בלי list=). רק כשהוא חיובי שווה
    להמתין (מוגבל בזכות PLAYLIST_METADATA_ENTRIES_CAP - כמה שניות) לתוצאת
    הזיהוי המדויקת: גם כדי להציג מספר נכון, וגם כי בלי זה יש race - לחיצה
    מהירה על אודיו/וידאו הייתה מקבלת "לא ידוע" תמיד כי ה-prefetch שרץ ברקע
    עוד לא הספיק לסיים."""
    if not is_youtube_playlist_url(url):
        return False

    prefetched_result = await get_youtube_download_options_result(context, url)

    if not prefetched_result.get('is_batch'):
        return False

    is_mix = prefetched_result.get('is_mix', False)
    entries_count = prefetched_result.get('batch_entries_count', 0)

    context.user_data['pending_batch_quality'] = selected_option
    context.user_data['pending_batch_quality_levels'] = quality_levels
    context.user_data['is_batch_mix'] = is_mix
    context.user_data['batch_playlist_info'] = prefetched_result.get('playlist_info')

    if is_mix:
        entries_count_label = (
            f'{entries_count}+' if entries_count >= PLAYLIST_METADATA_ENTRIES_CAP else str(entries_count)
        )
        prompt = (
            f'זיהיתי מיקס יוטיוב עם {entries_count_label} סרטונים זמינים לחילוץ.\nכמה להוריד?'
            if entries_count > 0
            else 'זיהיתי מיקס יוטיוב 🎵\nכמה להוריד?'
        )
    else:
        prompt = (
            f'זיהיתי פלייליסט עם {entries_count} סרטונים.\nכמה להוריד?'
            if entries_count > 0
            else 'זיהיתי פלייליסט יוטיוב 📃\nכמה להוריד?'
        )

    await message.edit_text(prompt, reply_markup=build_batch_count_keyboard(entries_count, is_mix=is_mix))
    return True


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
    # לא מוחקים את youtube_prefetch_task/url כאן! עדיין צריך אותם בהמשך -
    # אחרי שהמשתמש יבחר איכות, maybe_prompt_batch_count תלוי בהם כדי לדעת
    # כמה סרטונים יש בפלייליסט/מיקס בלי לחכות לרשת מחדש. הם יימחקו במקום
    # המתאים (batch_count_/quality_/cancel) כשבאמת אין בהם צורך יותר.
    reply_markup = build_quality_keyboard(download_options)
    await message.edit_text(prompt, reply_markup=reply_markup)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.data == 'cancel':
        clear_download_state(context)
        await query.answer('בוטל')
        await query.message.edit_text('בוטל. אפשר לשלוח קישור או חיפוש חדש.')
        return

    if query.data.startswith('search_pick_'):
        try:
            result_index = int(query.data.split('_')[-1])
        except ValueError:
            await query.answer('בחירה לא תקפה')
            return

        results = context.user_data.get('youtube_search_results') or []
        if result_index >= len(results):
            await query.answer('בחירה לא תקפה')
            await query.message.edit_text('התוצאות כבר לא תקפות. שלח חיפוש חדש.')
            return

        picked = results[result_index]
        url = picked['url']
        context.user_data.pop('youtube_search_results', None)
        context.user_data.pop('youtube_search_query', None)

        await query.answer()
        await begin_youtube_download_flow(
            query.message,
            context,
            url,
            edit_existing=True,
        )
        return

    if query.data.startswith('batch_count_'):
        count_suffix = query.data[len('batch_count_'):]
        if count_suffix == 'all':
            playlist_limit = None
        else:
            try:
                playlist_limit = int(count_suffix)
            except ValueError:
                await query.answer('בחירה לא תקפה')
                return

        url = context.user_data.get('current_url')
        selected_option = context.user_data.get('pending_batch_quality')
        quality_levels = context.user_data.get('pending_batch_quality_levels')

        if not url or not selected_option:
            await query.answer()
            await query.message.edit_text('משהו השתבש, אנא שלח את הקישור שוב.')
            return

        download_mode = selected_option.get('download_mode') or context.user_data.get('download_mode')

        # ל-maybe_prompt_batch_count כבר יש playlist_info מהזיהוי המדויק (היא
        # ממתינה לו) - נשתמש בו כדי לא לחלץ שוב את כל הפלייליסט/מיקס מאפס.
        # הוא מוגבל בכוונה ל-PLAYLIST_METADATA_ENTRIES_CAP entries (זיהוי מהיר)
        # - שמיש רק אם באמת יש בו מספיק בשביל הבחירה הנוכחית. אחרת (למשל
        # "הכל" בפלייליסט, או "100" במיקס גדול מ-20 שכבר נשלפו) - חובה לחלץ
        # מחדש עם הגבלה מתאימה, כדי שלא יורידו פחות ממה שהמשתמש בחר.
        cached_playlist_info_candidate = context.user_data.get('batch_playlist_info')
        cached_entries_available = (
            count_playlist_entries(cached_playlist_info_candidate)
            if cached_playlist_info_candidate else 0
        )
        cache_is_sufficient = (
            cached_playlist_info_candidate is not None
            and playlist_limit is not None
            and (
                cached_entries_available >= playlist_limit
                or cached_entries_available < PLAYLIST_METADATA_ENTRIES_CAP
            )
        )
        cached_playlist_info = cached_playlist_info_candidate if cache_is_sufficient else None

        await query.answer()
        context.user_data.pop('youtube_prefetch_task', None)
        context.user_data.pop('youtube_prefetch_url', None)
        context.user_data.pop('pending_batch_quality', None)
        context.user_data.pop('pending_batch_quality_levels', None)
        context.user_data.pop('is_batch_mix', None)
        context.user_data.pop('batch_playlist_info', None)

        # הערכת "משקל" הג'וב לצורך חישוב זמן המתנה בתור - מספר הסרטונים
        # שבאמת ירדו. אם המשתמש בחר "הכל" (playlist_limit=None) ואין לנו
        # ספירה מדויקת, נופלים על ברירת מחדל סבירה.
        job_weight = playlist_limit or cached_entries_available or 10

        status_message = await query.message.edit_text('מעבד את הבקשה... ⏳')
        # קריאה ישירה ל-download_playlist (ולא download_with_quality) כי כבר ידוע
        # בוודאות שזה פלייליסט/מיקס - כך נחסך שלב בדיקה חוזר שמחלץ הכל מאפס.
        cancel_token = CancellationToken()
        await enqueue_download_job(
            context,
            status_message,
            lambda: download_playlist(
                context,
                status_message,
                url,
                download_mode,
                selected_option,
                playlist_info=cached_playlist_info,
                playlist_limit=playlist_limit,
                should_cancel=cancel_token.is_cancelled,
            ),
            weight=job_weight,
            cancel_token=cancel_token,
        )
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

        if context.user_data.get('is_youtube') and await maybe_prompt_batch_count(
            query.message, context, url, selected_option, quality_options
        ):
            return

        context.user_data.pop('youtube_prefetch_task', None)
        context.user_data.pop('youtube_prefetch_url', None)
        status_message = await query.message.edit_text('מעבד את הבקשה... ⏳')

        cancel_token = CancellationToken()
        await enqueue_download_job(
            context,
            status_message,
            lambda: download_with_quality(
                context,
                status_message,
                url,
                download_mode,
                selected_option,
                quality_options,
                should_cancel=cancel_token.is_cancelled
            ),
            cancel_token=cancel_token,
        )
    else:
        # טיפול בבחירת פורמט (אודיו/וידאו)
        context.user_data['youtube_prefetch_waiting_for_choice'] = False
        await query.answer()
        download_mode = query.data  # 'audio' or 'video'
        context.user_data['download_mode'] = download_mode
        
        is_youtube = context.user_data.get('is_youtube', False)
        
        if download_mode == 'audio':
            quality = build_youtube_audio_option() if is_youtube else DEFAULT_FORMAT
            current_url = context.user_data.get('current_url')

            if is_youtube and await maybe_prompt_batch_count(
                query.message, context, current_url, quality, None
            ):
                return

            context.user_data.pop('youtube_prefetch_task', None)
            context.user_data.pop('youtube_prefetch_url', None)
            status_message = await query.message.edit_text('מעבד את הבקשה... ⏳')
            cancel_token = CancellationToken()
            await enqueue_download_job(
                context,
                status_message,
                lambda: download_with_quality(
                    context,
                    status_message,
                    current_url,
                    download_mode,
                    quality,
                    context.user_data.get('youtube_download_options') if is_youtube else None,
                    should_cancel=cancel_token.is_cancelled
                ),
                cancel_token=cancel_token,
            )
        elif not is_youtube:
            # עבור פלטפורמות שאינן יוטיוב - מתחילים הורדה מיד באיכות הטובה ביותר
            status_message = await query.message.edit_text('מעבד את הבקשה... ⏳')
            quality = DEFAULT_FORMAT
            current_url = context.user_data.get('current_url')
            cancel_token = CancellationToken()
            await enqueue_download_job(
                context,
                status_message,
                lambda: download_with_quality(
                    context,
                    status_message,
                    current_url,
                    download_mode,
                    quality,
                    None,
                    should_cancel=cancel_token.is_cancelled
                ),
                cancel_token=cancel_token,
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
