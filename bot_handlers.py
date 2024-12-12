from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from logger_setup import logger
from config import QUALITY_LEVELS
from download_manager import download_with_quality

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
    
    logger.info(f"Starting download process for URL: {url} in mode: {download_mode}")
    
    if not url:
        await query.message.reply_text('משהו השתבש, אנא שלח את הקישור שוב.')
        return
    
    current_quality_index = context.user_data.get('current_quality_index', 0)
    status_message = await query.message.reply_text('מתחיל בהורדה... ⏳')
    
    await download_with_quality(
        context,
        status_message,
        url,
        download_mode,
        QUALITY_LEVELS[current_quality_index],
        QUALITY_LEVELS
    ) 