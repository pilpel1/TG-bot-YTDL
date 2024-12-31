from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from logger_setup import logger
from config import QUALITY_LEVELS
from download_manager import download_with_quality
import random

THANK_YOU_RESPONSES = [
    "בכיף! 😊",
    "שמח לעזור! 🌟",
    "אין בעד מה! 💫",
    "תהנה/י! 🎵",
    "לשירותך! 🤖",
    "בשמחה! ✨"
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'שלום! 👋\n'
        'אני בוט להורדת סרטונים ממגוון אתרים כמו יוטיוב, פייסבוק, אינסטגרם, טיקטוק ועוד.\n'
        'פשוט שלח לי קישור ואני אשאל אותך אם תרצה להוריד אודיו או וידאו.'
    )

async def ask_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    context.user_data['current_url'] = url
    
    keyboard = [
        [
            InlineKeyboardButton("אודיו 🎵", callback_data='audio'),
            InlineKeyboardButton("וידאו 🎥", callback_data='video')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('מה תרצה להוריד?', reply_markup=reply_markup)

async def ask_quality(message, download_mode):
    """שואל את המשתמש באיזו איכות הוא רוצה להוריד"""
    keyboard = []
    
    for i, quality in enumerate(QUALITY_LEVELS):
        keyboard.append([
            InlineKeyboardButton(
                quality['quality_name'],
                callback_data=f'quality_{i}'
            )
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.edit_text('באיזו איכות להוריד את הוידאו?', reply_markup=reply_markup)

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
        status_message = await query.message.edit_text('מתחיל בהורדה... ⏳')
        
        await download_with_quality(
            context,
            status_message,
            url,
            download_mode,
            QUALITY_LEVELS[quality_index],
            QUALITY_LEVELS
        )
    else:
        # טיפול בבחירת פורמט (אודיו/וידאו)
        download_mode = query.data  # 'audio' or 'video'
        context.user_data['download_mode'] = download_mode
        
        if download_mode == 'audio':
            # עבור אודיו - מתחילים הורדה מיד באיכות הרגילה
            status_message = await query.message.edit_text('מתחיל בהורדה... ⏳')
            await download_with_quality(
                context,
                status_message,
                context.user_data.get('current_url'),
                download_mode,
                QUALITY_LEVELS[1],  # איכות רגילה
                QUALITY_LEVELS
            )
        else:
            # עבור וידאו - שואלים על איכות
            await ask_quality(query.message, download_mode) 

async def handle_thank_you(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מטפל בהודעות תודה"""
    response = random.choice(THANK_YOU_RESPONSES)
    await update.message.reply_text(response) 