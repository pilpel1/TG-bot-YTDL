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
    MAINTENANCE_USER_MESSAGE,
    CHANNEL_WATCH_MAX_PER_USER,
)
from download_manager import download_with_quality, download_playlist
from download_queue import CancellationToken
from user_settings import (
    get_search_mode,
    set_search_mode,
    remember_chat,
    remember_from_update,
    list_known_chat_ids,
    format_known_user_label,
    list_channel_subs,
    get_channel_sub,
    add_channel_sub,
    update_channel_sub,
    remove_channel_sub,
    find_duplicate_channel,
    normalize_source_list,
    normalize_delivery_list,
)
from ytdlp_updater import is_maintenance_mode, track_ytdlp_metadata
from channel_watch import (
    resolve_channel,
    fetch_source_entries,
    initialize_baselines,
    is_youtube_url,
    sources_label_he,
    delivery_label_he,
    description_label_he,
    format_watch_schedule_he,
)
from broadcast import is_admin, list_broadcast_targets, run_broadcast
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


async def reply_maintenance(update=None, query=None, message=None):
    """מודיע למשתמש שהבוט בתחזוקה. לא מתחיל עבודת yt-dlp חדשה."""
    if query is not None:
        try:
            await query.answer()
        except Exception:
            pass
        target = query.message
        if target:
            try:
                await target.edit_text(MAINTENANCE_USER_MESSAGE)
                return
            except Exception:
                pass
            try:
                await target.reply_text(MAINTENANCE_USER_MESSAGE)
                return
            except Exception:
                pass
    if message is not None:
        await message.reply_text(MAINTENANCE_USER_MESSAGE)
        return
    if update is not None and update.effective_message:
        await update.effective_message.reply_text(MAINTENANCE_USER_MESSAGE)


async def enqueue_download_job(context, status_message, coro_factory, weight=1, cancel_token=None):
    """מכניס ג'וב הורדה לתור הגלובלי ומחזיר מיד - לא מחכה לסיום ההורדה.
    כך ה-handler משתחרר ומאפשר לבוט להמשיך להגיב למשתמשים אחרים בזמן
    שההורדה עצמה רצה ברקע דרך worker התור.

    weight: מספר "יחידות עבודה" משוער בג'וב (1 לסרטון בודד, N לפלייליסט של
    N סרטונים) - רק לצורך הערכת זמן, לא משפיע על הסדר.

    cancel_token: אותו טוקן שכבר נסגר (closure) לתוך coro_factory כ-
    should_cancel - מועבר גם לתור כדי ש-/stop יוכל לסמן אותו דרך cancel()."""
    if is_maintenance_mode():
        logger.info("Skipped enqueue: maintenance mode is active")
        try:
            await status_message.edit_text(MAINTENANCE_USER_MESSAGE)
        except Exception:
            pass
        return None

    download_queue = context.bot_data['download_queue']
    return await download_queue.enqueue(
        chat_id=status_message.chat_id,
        status_message=status_message,
        coro_factory=coro_factory,
        weight=weight,
        cancel_token=cancel_token,
    )


async def remember_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """group=-1: רושם כל משתמש שנוגע בבוט, בלי לבלוע את ההודעה."""
    remember_from_update(update)


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


def clear_channel_wizard(context):
    context.user_data.pop('channel_wizard', None)

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


def is_search_mode_enabled(context, user_id=None) -> bool:
    """מצב חיפוש — פר-משתמש, נשמר לדיסק ושורד ריסטארט.

    קודם נטען מ-user_data (זיכרון); אם עדיין לא נטען בהרצה הנוכחית —
    נשלף מ-data/search_modes.json. בלי user_id ובלי ערך בזיכרון → כבוי."""
    if 'search_mode' not in context.user_data:
        if user_id is None:
            return False
        context.user_data['search_mode'] = get_search_mode(user_id)
    return bool(context.user_data['search_mode'])


def build_bot_commands(search_mode_on: bool = False, include_admin: bool = False):
    """בונה רשימת פקודות לתפריט טלגרם, עם סטטוס מצב חיפוש בתיאור."""
    search_desc = (
        'מצב חיפוש (פעיל כעת)'
        if search_mode_on
        else 'מצב חיפוש (כבוי כעת)'
    )
    commands = [
        BotCommand('start', 'הודעת פתיחה'),
        BotCommand('help', 'עזרה, פקודות ומגבלת קבצים'),
        BotCommand('search_mode', search_desc),
        BotCommand('channels', 'מעקב אחרי ערוצי יוטיוב'),
        BotCommand('stop', 'ביטול הורדה פעילה או ממתינה'),
        BotCommand('version', 'גרסה נוכחית ושינויים'),
    ]
    if include_admin:
        commands.extend([
            BotCommand('broadcast', 'שידור הודעה לכל המשתמשים (אדמין)'),
            BotCommand('users', 'רשימת משתמשים (אדמין)'),
            BotCommand('mode', 'מצב שרת ומגבלת קבצים (אדמין)'),
        ])
    return commands


async def sync_user_command_menu(bot, chat_id, search_mode_on: bool):
    """מעדכן את תפריט הפקודות רק לצ'אט הזה (BotCommandScopeChat).

    ככה סטטוס 'פעיל/כבוי' של משתמש א' לא מופיע אצל משתמש ב'.
    נקרא גם ב-/start ו-/help כדי לתקן תיאור ישן אחרי ריסטארט בוט
    (user_data בזיכרון מתאפס, אבל תפריט טלגרם נשאר עד שמעדכנים)."""
    remember_chat(chat_id)
    try:
        await bot.set_my_commands(
            build_bot_commands(search_mode_on, include_admin=is_admin(chat_id)),
            scope=BotCommandScopeChat(chat_id=chat_id),
        )
    except Exception as e:
        logger.warning(f"Could not sync command menu for chat {chat_id}: {e}")


async def ensure_command_menu_synced(context, chat_id, user_id):
    """מרענן תפריט פעם אחת בהרצה הזו — תופס משתמשים עם תפריט ישן בלי /channels."""
    if context.user_data.get('commands_menu_synced'):
        return
    await sync_user_command_menu(
        context.bot,
        chat_id,
        is_search_mode_enabled(context, user_id),
    )
    context.user_data['commands_menu_synced'] = True


async def refresh_all_user_command_menus(bot):
    """אחרי עליית הבוט: דוחף את רשימת הפקודות העדכנית לכל צ'אט מוכר."""
    chat_ids = list_known_chat_ids()
    for chat_id in chat_ids:
        try:
            numeric_id = int(chat_id)
        except (TypeError, ValueError):
            continue
        await sync_user_command_menu(bot, numeric_id, get_search_mode(numeric_id))
    if chat_ids:
        logger.info(f"Refreshed command menus for {len(chat_ids)} chats")


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
        with track_ytdlp_metadata():
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
    """מפעיל/מכבה מצב חיפוש טקסט חופשי ביוטיוב (פר-משתמש, נשמר לדיסק)."""
    user_id = update.effective_user.id
    enabled = not is_search_mode_enabled(context, user_id)
    context.user_data['search_mode'] = enabled
    set_search_mode(user_id, enabled)
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


def _checked(label, selected):
    return f'✓ {label}' if selected else label


def build_channels_list_keyboard(subs):
    keyboard = [
        [InlineKeyboardButton(sub.get('channel_label') or f'ערוץ {index + 1}', callback_data=f'ch_e:{index}')]
        for index, sub in enumerate(subs)
    ]
    if len(subs) < CHANNEL_WATCH_MAX_PER_USER:
        keyboard.append([InlineKeyboardButton('➕ הוסף ערוץ', callback_data='ch_add')])
    return InlineKeyboardMarkup(keyboard) if keyboard else InlineKeyboardMarkup([
        [InlineKeyboardButton('➕ הוסף ערוץ', callback_data='ch_add')]
    ])


def build_channels_list_text(subs):
    count = len(subs)
    header = (
        f'מעקב אחרי ערוצי יוטיוב ({count}/{CHANNEL_WATCH_MAX_PER_USER})\n'
        f'בודק {format_watch_schedule_he()} — לא ברגע שהסרטון עולה.'
    )
    if not subs:
        return header + '\n\nאין ערוצים במעקב עדיין.'
    lines = [header, '']
    for sub in subs:
        lines.append(
            f"• {sub.get('channel_label') or 'ערוץ'} — "
            f"{sources_label_he(sub.get('sources'))} · "
            f"{delivery_label_he(sub.get('delivery'))} · "
            f"{description_label_he(sub.get('include_description'))}"
        )
    lines.append('\nלחץ על ערוץ כדי לערוך.')
    return '\n'.join(lines)


def build_channel_edit_text(sub):
    label = sub.get('channel_label') or 'ערוץ'
    url = sub.get('channel_url') or ''
    return (
        f'{label}\n{url}\n\n'
        f'מה לעקוב: {sources_label_he(sub.get("sources"))}\n'
        f'מה לשלוח: {delivery_label_he(sub.get("delivery"))}\n'
        f'תיאור: {description_label_he(sub.get("include_description"))}\n\n'
        'לחץ על כפתור כדי לשנות. מה שלא נוגעים בו נשאר כמו שהוא.'
    )


def build_channel_edit_keyboard(sub, index):
    sources = sub.get('sources') or []
    delivery = sub.get('delivery') or []
    include_description = bool(sub.get('include_description'))
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_checked('סרטונים', 'videos' in sources), callback_data=f'ch_tv:{index}'),
            InlineKeyboardButton(_checked('שורטס', 'shorts' in sources), callback_data=f'ch_ts:{index}'),
        ],
        [
            InlineKeyboardButton(_checked('אודיו', 'audio' in delivery), callback_data=f'ch_ta:{index}'),
            InlineKeyboardButton(_checked('וידאו', 'video' in delivery), callback_data=f'ch_td:{index}'),
        ],
        [
            InlineKeyboardButton(
                _checked('עם תיאור', include_description),
                callback_data=f'ch_tc:{index}',
            ),
        ],
        [InlineKeyboardButton('🗑 הסר מעקב', callback_data=f'ch_rm:{index}')],
        [InlineKeyboardButton('« חזרה', callback_data='ch_list')],
    ])


def build_wizard_sources_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('סרטונים', callback_data='ch_src:videos')],
        [InlineKeyboardButton('שורטס', callback_data='ch_src:shorts')],
        [InlineKeyboardButton('שניהם', callback_data='ch_src:both')],
        [InlineKeyboardButton('❌ ביטול', callback_data='ch_cancel')],
    ])


def build_wizard_delivery_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('אודיו 🎵', callback_data='ch_dlv:audio')],
        [InlineKeyboardButton('וידאו 🎥', callback_data='ch_dlv:video')],
        [InlineKeyboardButton('שניהם', callback_data='ch_dlv:both')],
        [InlineKeyboardButton('❌ ביטול', callback_data='ch_cancel')],
    ])


def build_wizard_description_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('עם תיאור', callback_data='ch_dsc:1')],
        [InlineKeyboardButton('בלי תיאור', callback_data='ch_dsc:0')],
        [InlineKeyboardButton('❌ ביטול', callback_data='ch_cancel')],
    ])


def build_wizard_confirm_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('אישור ✅', callback_data='ch_ok')],
        [InlineKeyboardButton('❌ ביטול', callback_data='ch_cancel')],
    ])


def build_wizard_confirm_text(wizard):
    return (
        f"לאשר מעקב אחרי {wizard.get('channel_label') or 'הערוץ'}?\n"
        f"{wizard.get('channel_url') or ''}\n\n"
        f"מה לעקוב: {sources_label_he(wizard.get('sources'))}\n"
        f"מה לשלוח: {delivery_label_he(wizard.get('delivery'))}\n"
        f"תיאור: {description_label_he(wizard.get('include_description'))}\n\n"
        f'סרטונים שכבר עלו לא יישלחו.\n'
        f'חדשים יגיעו בבדיקה הבאה ({format_watch_schedule_he()}).'
    )


async def show_channels_list(message, user_id, *, edit_existing=False):
    subs = list_channel_subs(user_id)
    text = build_channels_list_text(subs)
    markup = build_channels_list_keyboard(subs)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        return
    await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


async def show_channel_edit(message, user_id, index):
    sub = get_channel_sub(user_id, index)
    if not sub:
        await message.edit_text('הערוץ כבר לא במעקב.')
        return
    await message.edit_text(
        build_channel_edit_text(sub),
        reply_markup=build_channel_edit_keyboard(sub, index),
        disable_web_page_preview=True,
    )


async def channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """רשימת ערוצים במעקב + הוספה/עריכה."""
    await ensure_command_menu_synced(
        context, update.effective_chat.id, update.effective_user.id
    )
    clear_channel_wizard(context)
    await show_channels_list(update.message, update.effective_user.id)


async def start_channel_add(message, context, user_id):
    if len(list_channel_subs(user_id)) >= CHANNEL_WATCH_MAX_PER_USER:
        await message.edit_text(
            f'הגעת למקסימום {CHANNEL_WATCH_MAX_PER_USER} ערוצים.\n'
            'אפשר להסיר ערוץ קיים כדי לפנות מקום.'
        )
        return
    context.user_data['channel_wizard'] = {'step': 'awaiting_url'}
    await message.edit_text(
        'שלח קישור לערוץ יוטיוב (למשל youtube.com/@name או /channel/UC...).\n'
        'אפשר גם קישור לסרטון מהערוץ.\n\n'
        'לביטול: /channels'
    )


async def handle_channel_wizard_url(update, context, text):
    message = update.message
    words = text.split() if text else []
    urls = [word for word in words if is_valid_url(word)]
    if not urls:
        await message.reply_text(
            'לא מצאתי קישור. שלח קישור לערוץ יוטיוב, או /channels לביטול.'
        )
        return
    url = urls[0]
    if not is_youtube_url(url):
        await message.reply_text('זה לא קישור יוטיוב. שלח קישור לערוץ, או /channels לביטול.')
        return
    if is_maintenance_mode():
        await reply_maintenance(update=update, message=message)
        return

    status = await message.reply_text('בודק את הערוץ... ⏳')
    try:
        with track_ytdlp_metadata():
            resolved = await asyncio.to_thread(resolve_channel, url)
    except Exception as e:
        logger.warning(f"Could not resolve channel from {url}: {e}")
        await status.edit_text('לא הצלחתי לזהות את הערוץ. נסה קישור אחר, או /channels לביטול.')
        return

    user_id = update.effective_user.id
    duplicate = find_duplicate_channel(
        user_id,
        channel_id=resolved.get('channel_id'),
        channel_url=resolved.get('channel_url'),
    )
    if duplicate is not None:
        clear_channel_wizard(context)
        await status.edit_text(
            f"{resolved.get('channel_label')} כבר במעקב.\nאפשר לערוך אותו מהרשימה.",
            reply_markup=build_channels_list_keyboard(list_channel_subs(user_id)),
        )
        return
    if len(list_channel_subs(user_id)) >= CHANNEL_WATCH_MAX_PER_USER:
        clear_channel_wizard(context)
        await status.edit_text(f'הגעת למקסימום {CHANNEL_WATCH_MAX_PER_USER} ערוצים.')
        return

    wizard = context.user_data.get('channel_wizard') or {}
    wizard.update({
        'step': 'sources',
        'channel_url': resolved['channel_url'],
        'channel_id': resolved.get('channel_id') or '',
        'channel_label': resolved['channel_label'],
    })
    context.user_data['channel_wizard'] = wizard
    await status.edit_text(
        f"מצאתי: {resolved['channel_label']}\nמה לעקוב?",
        reply_markup=build_wizard_sources_keyboard(),
        disable_web_page_preview=True,
    )


async def finalize_channel_add(message, context, user_id):
    wizard = context.user_data.get('channel_wizard') or {}
    if not wizard.get('channel_url'):
        clear_channel_wizard(context)
        await message.edit_text('משהו השתבש. נסה שוב עם /channels.')
        return

    if is_maintenance_mode():
        await message.edit_text(MAINTENANCE_USER_MESSAGE)
        return

    await message.edit_text('שומר ומתעלם מסרטונים שכבר עלו... ⏳')
    source_entries = {}
    for source_key in wizard.get('sources') or ['videos']:
        try:
            with track_ytdlp_metadata():
                source_entries[source_key] = await asyncio.to_thread(
                    fetch_source_entries,
                    wizard['channel_url'],
                    source_key,
                )
        except Exception as e:
            logger.warning(f"Baseline fetch failed for {wizard.get('channel_label')} /{source_key}: {e}")
            source_entries[source_key] = []

    sub = initialize_baselines({
        'channel_url': wizard['channel_url'],
        'channel_id': wizard.get('channel_id') or '',
        'channel_label': wizard.get('channel_label') or wizard['channel_url'],
        'sources': wizard.get('sources') or ['videos'],
        'delivery': wizard.get('delivery') or ['audio'],
        'include_description': bool(wizard.get('include_description')),
        'notified_video_ids': [],
        'sources_state': {},
    }, source_entries)

    _index, error = add_channel_sub(user_id, sub)
    clear_channel_wizard(context)
    if error == 'limit':
        await message.edit_text(f'הגעת למקסימום {CHANNEL_WATCH_MAX_PER_USER} ערוצים.')
        return
    if error == 'duplicate':
        await message.edit_text('הערוץ כבר במעקב.')
        return
    await message.edit_text(
        f"מעכשיו אעקוב אחרי {sub['channel_label']}.\n"
        f'סרטונים חדשים יגיעו בבדיקה הבאה ({format_watch_schedule_he()}). '
        'מה שכבר עלה לא יישלח.',
        disable_web_page_preview=True,
    )
    await show_channels_list(message, user_id)


def _parse_channel_index(data, prefix):
    try:
        return int(data[len(prefix):])
    except ValueError:
        return None


async def handle_channel_callback(query, context):
    data = query.data
    user_id = query.from_user.id
    message = query.message

    if data == 'ch_list':
        clear_channel_wizard(context)
        await query.answer()
        await show_channels_list(message, user_id, edit_existing=True)
        return

    if data == 'ch_cancel':
        clear_channel_wizard(context)
        await query.answer('בוטל')
        await show_channels_list(message, user_id, edit_existing=True)
        return

    if data == 'ch_add':
        await query.answer()
        await start_channel_add(message, context, user_id)
        return

    if data.startswith('ch_src:'):
        wizard = context.user_data.get('channel_wizard')
        if not wizard:
            await query.answer('הבחירה פגה. /channels')
            return
        choice = data.split(':', 1)[1]
        wizard['sources'] = ['videos', 'shorts'] if choice == 'both' else [choice]
        wizard['step'] = 'delivery'
        context.user_data['channel_wizard'] = wizard
        await query.answer()
        await message.edit_text(
            f"{wizard.get('channel_label')}\nמה לשלוח כשיש סרטון חדש?",
            reply_markup=build_wizard_delivery_keyboard(),
        )
        return

    if data.startswith('ch_dlv:'):
        wizard = context.user_data.get('channel_wizard')
        if not wizard:
            await query.answer('הבחירה פגה. /channels')
            return
        choice = data.split(':', 1)[1]
        wizard['delivery'] = ['audio', 'video'] if choice == 'both' else [choice]
        wizard['step'] = 'description'
        context.user_data['channel_wizard'] = wizard
        await query.answer()
        await message.edit_text(
            f"{wizard.get('channel_label')}\nלצרף את תיאור הסרטון מהיוטיוב?",
            reply_markup=build_wizard_description_keyboard(),
        )
        return

    if data.startswith('ch_dsc:'):
        wizard = context.user_data.get('channel_wizard')
        if not wizard:
            await query.answer('הבחירה פגה. /channels')
            return
        wizard['include_description'] = data.endswith(':1')
        wizard['step'] = 'confirm'
        context.user_data['channel_wizard'] = wizard
        await query.answer()
        await message.edit_text(
            build_wizard_confirm_text(wizard),
            reply_markup=build_wizard_confirm_keyboard(),
            disable_web_page_preview=True,
        )
        return

    if data == 'ch_ok':
        wizard = context.user_data.get('channel_wizard')
        if not wizard:
            await query.answer('הבחירה פגה. /channels')
            return
        await query.answer()
        await finalize_channel_add(message, context, user_id)
        return

    if data.startswith('ch_e:'):
        index = _parse_channel_index(data, 'ch_e:')
        if index is None:
            await query.answer('בחירה לא תקפה')
            return
        await query.answer()
        await show_channel_edit(message, user_id, index)
        return

    if data.startswith('ch_rmok:'):
        index = _parse_channel_index(data, 'ch_rmok:')
        if index is None:
            await query.answer('בחירה לא תקפה')
            return
        if not remove_channel_sub(user_id, index):
            await query.answer('הערוץ כבר לא במעקב')
            await show_channels_list(message, user_id, edit_existing=True)
            return
        await query.answer('הוסר')
        await show_channels_list(message, user_id, edit_existing=True)
        return

    if data.startswith('ch_rm:'):
        index = _parse_channel_index(data, 'ch_rm:')
        sub = get_channel_sub(user_id, index) if index is not None else None
        if sub is None:
            await query.answer('הערוץ כבר לא במעקב')
            await show_channels_list(message, user_id, edit_existing=True)
            return
        await query.answer()
        await message.edit_text(
            f"להסיר מעקב אחרי {sub.get('channel_label') or 'הערוץ'}?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('כן, להסיר', callback_data=f'ch_rmok:{index}')],
                [InlineKeyboardButton('לא', callback_data=f'ch_e:{index}')],
            ]),
        )
        return

    toggle_map = {
        'ch_tv:': ('sources', 'videos'),
        'ch_ts:': ('sources', 'shorts'),
        'ch_ta:': ('delivery', 'audio'),
        'ch_td:': ('delivery', 'video'),
    }
    for prefix, (field, value) in toggle_map.items():
        if data.startswith(prefix):
            index = _parse_channel_index(data, prefix)
            sub = get_channel_sub(user_id, index) if index is not None else None
            if sub is None:
                await query.answer('הערוץ כבר לא במעקב')
                return
            current = list(sub.get(field) or [])
            if value in current:
                if len(current) == 1:
                    await query.answer('חייבים לפחות אפשרות אחת', show_alert=True)
                    return
                current.remove(value)
            else:
                current.append(value)
            if field == 'sources':
                current = normalize_source_list(current)
            else:
                current = normalize_delivery_list(current)
            update_channel_sub(user_id, index, **{field: current})
            await query.answer('עודכן')
            await show_channel_edit(message, user_id, index)
            return

    if data.startswith('ch_tc:'):
        index = _parse_channel_index(data, 'ch_tc:')
        sub = get_channel_sub(user_id, index) if index is not None else None
        if sub is None:
            await query.answer('הערוץ כבר לא במעקב')
            return
        update_channel_sub(user_id, index, include_description=not sub.get('include_description'))
        await query.answer('עודכן')
        await show_channel_edit(message, user_id, index)
        return

    await query.answer('בחירה לא תקפה')


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
    search_mode_on = is_search_mode_enabled(context, update.effective_user.id)
    await sync_user_command_menu(
        context.bot,
        update.effective_chat.id,
        search_mode_on,
    )
    await update.message.reply_text(
        'שלום! 👋\n'
        f'{SUPPORTED_SITES_MESSAGE}\n'
        'שלח קישור להורדה, או /search_mode לחיפוש ביוטיוב לפי טקסט.\n'
        f'מעקב ערוץ ({format_watch_schedule_he()}): /channels\n'
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
    search_mode_on = is_search_mode_enabled(context, update.effective_user.id)
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
        f'• מעקב ערוץ יוטיוב — /channels ({format_watch_schedule_he()}, לא מיידי)\n'
        '• אם יש קישור בהודעה, אתייחס רק אליו\n\n'
        'פקודות:\n'
        '/start — הודעת פתיחה\n'
        '/help — העזרה הזאת\n'
        '/search_mode — הפעלה/כיבוי חיפוש טקסט (כרגע: '
        f'{search_status})\n'
        '/channels — מעקב אחרי ערוצי יוטיוב\n'
        '/stop — ביטול הורדה פעילה או ממתינה בתור\n'
        '/version — גרסה נוכחית ושינויים\n\n'
        f'{build_file_limit_summary()}'
    )

async def ask_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat and update.effective_user:
        await ensure_command_menu_synced(
            context, update.effective_chat.id, update.effective_user.id
        )

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
    search_mode_on = is_search_mode_enabled(context, update.effective_user.id)

    wizard = context.user_data.get('channel_wizard')
    if wizard and wizard.get('step') == 'awaiting_url':
        await handle_channel_wizard_url(update, context, text)
        return

    if is_admin(update.effective_user.id) and context.user_data.get('awaiting_broadcast'):
        await offer_broadcast_confirm(message, context, message)
        return

    # קישור תמיד מנצח — גם אם יש מסביב טקסט ארוך / "תודה" / מצב חיפוש דלוק
    if valid_urls:
        if is_maintenance_mode():
            await reply_maintenance(update=update, message=message)
            return

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
            if is_maintenance_mode():
                await reply_maintenance(update=update, message=message)
                return
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
    with track_ytdlp_metadata():
        return await _prefetch_youtube_download_options(url)


async def _prefetch_youtube_download_options(url):
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

    if query.data.startswith('bc_'):
        await handle_broadcast_callback(query, context)
        return

    if query.data.startswith('ch_'):
        await handle_channel_callback(query, context)
        return

    if is_maintenance_mode():
        await reply_maintenance(update=update, query=query)
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


async def mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ניטור פנימי: מצב שרת / מגבלת קבצים (לא בתפריט הפקודות)."""
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


def _clear_broadcast_state(context):
    context.user_data.pop('awaiting_broadcast', None)
    context.user_data.pop('broadcast_from_chat_id', None)
    context.user_data.pop('broadcast_message_id', None)


def format_broadcast_recipient_lines(targets) -> str:
    """שמות ליעד שידור. שם חסר → המספר, בלי להפיל את השידור."""
    lines = []
    for chat_id in targets:
        try:
            lines.append(f'• {format_known_user_label(chat_id)}')
        except Exception:
            lines.append(f'• {chat_id}')
    return '\n'.join(lines)


def build_broadcast_confirm_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('שגר ✅', callback_data='bc_ok')],
        [InlineKeyboardButton('בטל', callback_data='bc_no')],
    ])


async def offer_broadcast_confirm(reply_to, context, source_message):
    """מציג אישור שידור להודעה שכבר קיימת בצ'אט."""
    from_chat_id = source_message.chat_id
    message_id = source_message.message_id
    targets = list_broadcast_targets()
    if not targets:
        _clear_broadcast_state(context)
        await reply_to.reply_text('אין משתמשים ברשימה לשידור.')
        return

    context.user_data['awaiting_broadcast'] = False
    context.user_data['broadcast_from_chat_id'] = from_chat_id
    context.user_data['broadcast_message_id'] = message_id
    try:
        await backfill_known_user_profiles(context.bot)
    except Exception as e:
        logger.warning(f"Broadcast name backfill failed: {e}")
    names = format_broadcast_recipient_lines(targets)
    await reply_to.reply_text(
        f'לשגר את ההודעה הזו ל-{len(targets)} משתמשים?\n'
        f'{names}',
        reply_markup=build_broadcast_confirm_keyboard(),
        quote=True,
    )


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/broadcast — אדמין בלבד, לא בתפריט. בלי ID ב-.env הפקודה שותקת."""
    user = update.effective_user
    message = update.message
    if not user or not message or not is_admin(user.id):
        return

    _clear_broadcast_state(context)
    replied = message.reply_to_message
    if replied:
        await offer_broadcast_confirm(message, context, replied)
        return

    context.user_data['awaiting_broadcast'] = True
    await message.reply_text(
        'שלח עכשיו את ההודעה או התמונה לשידור.\n'
        'אפשר גם להשיב עם /broadcast על הודעה שכבר שלחת כאן.'
    )


async def handle_broadcast_callback(query, context):
    if not is_admin(query.from_user.id):
        await query.answer()
        return

    if query.data == 'bc_no':
        _clear_broadcast_state(context)
        await query.answer('בוטל')
        await query.message.edit_text('השידור בוטל.')
        return

    if query.data != 'bc_ok':
        await query.answer()
        return

    if context.bot_data.get('broadcast_running'):
        await query.answer('שידור כבר רץ')
        return

    from_chat_id = context.user_data.get('broadcast_from_chat_id')
    message_id = context.user_data.get('broadcast_message_id')
    if from_chat_id is None or message_id is None:
        await query.answer('אין הודעה לשידור')
        await query.message.edit_text('אין הודעה שמורה לשידור. שלח /broadcast שוב.')
        return

    targets = list_broadcast_targets()
    if not targets:
        _clear_broadcast_state(context)
        await query.answer()
        await query.message.edit_text('אין משתמשים ברשימה לשידור.')
        return

    context.bot_data['broadcast_running'] = True
    _clear_broadcast_state(context)
    await query.answer()
    await query.message.edit_text(f'משגר ל-{len(targets)} משתמשים...')

    async def on_progress(sent, blocked, failed, total):
        try:
            await query.message.edit_text(
                f'משגר... {sent + blocked + failed}/{total}'
            )
        except Exception:
            pass

    try:
        sent, blocked, failed = await run_broadcast(
            context.bot,
            from_chat_id,
            message_id,
            targets,
            on_progress=on_progress,
        )
    finally:
        context.bot_data['broadcast_running'] = False

    summary = f'השידור הסתיים.\nנשלח: {sent}'
    if blocked:
        summary += f'\nחסמו את הבוט: {blocked}'
    if failed:
        summary += f'\nנכשל: {failed}'
    await query.message.edit_text(summary)


async def backfill_known_user_profiles(bot):
    """משלים שמות ל-IDs שכבר שמורים, דרך getChat."""
    for chat_id in list_known_chat_ids():
        label = format_known_user_label(chat_id)
        if label != str(chat_id):
            continue
        try:
            chat = await bot.get_chat(int(chat_id))
            remember_chat(chat_id, chat=chat)
        except Exception as e:
            logger.warning(f"Could not resolve name for chat {chat_id}: {e}")


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/users — אדמין בלבד. רשימת מי שמוכר לבוט, עם שמות."""
    user = update.effective_user
    message = update.message
    if not user or not message or not is_admin(user.id):
        return

    try:
        await backfill_known_user_profiles(context.bot)
    except Exception as e:
        logger.warning(f"Could not backfill user names: {e}")
    chat_ids = list_known_chat_ids()
    if not chat_ids:
        await message.reply_text('אין עדיין משתמשים שמורים.')
        return

    names = format_broadcast_recipient_lines(chat_ids)
    await message.reply_text(
        f'{len(chat_ids)} משתמשים ידועים:\n{names}'
    )
