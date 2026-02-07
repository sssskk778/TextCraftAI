import os
import logging
from enum import Enum
from dataclasses import dataclass

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode, ChatAction
from mistralai import Mistral
from dotenv import load_dotenv

PORT = int(os.getenv("PORT", 8080))  # 8080 по умолчанию
load_dotenv()

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not MISTRAL_API_KEY or not TELEGRAM_BOT_TOKEN:
    print("❌ Ошибка: Проверьте файл .env")
    exit(1)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

client = Mistral(api_key=MISTRAL_API_KEY)
MODEL = "mistral-small-latest"

SELECTING_ACTION, EDITING_TEXT = range(2)


class EditAction(Enum):
    FIX = "исправить"
    SHORTEN = "сократить"
    IMPROVE = "улучшить"
    FORMAL = "формальный"
    FRIENDLY = "дружеский"
    REPHRASE = "перефразировать"
    CONTINUE = "продолжить"


@dataclass
class UserData:
    current_text: str = ""
    history: list = None

    def __post_init__(self):
        if self.history is None:
            self.history = []


user_sessions = {}


def get_main_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("✏️ Исправить", callback_data=EditAction.FIX.value),
            InlineKeyboardButton("✂️ Сократить", callback_data=EditAction.SHORTEN.value),
        ],
        [
            InlineKeyboardButton("🚀 Улучшить", callback_data=EditAction.IMPROVE.value),
            InlineKeyboardButton("🔄 Перефразировать", callback_data=EditAction.REPHRASE.value),
        ],
        [
            InlineKeyboardButton("🎩 Формальный", callback_data=EditAction.FORMAL.value),
            InlineKeyboardButton("😊 Дружеский", callback_data=EditAction.FRIENDLY.value),
        ],
        [
            InlineKeyboardButton("➡️ Продолжить текст", callback_data=EditAction.CONTINUE.value)
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_after_edit_keyboard():
    keyboard = [
        [InlineKeyboardButton("📝 Редактировать дальше", callback_data="edit_more")],
        [InlineKeyboardButton("🏁 Завершить", callback_data="done")],
    ]
    return InlineKeyboardMarkup(keyboard)


PROMPTS = {
    EditAction.FIX: """Исправь все орфографические, пунктуационные и грамматические ошибки в тексте ниже. 
Сохрани оригинальный стиль и смысл. Не добавляй комментарии, только исправленный текст.

Текст: {text}""",

    EditAction.SHORTEN: """Сократи этот текст, убрав лишние слова, повторы и воду. 
Оставь только суть и ключевые идеей. Сохрани основной смысл. Цель - сделать текст короче на 30-50%. Не добавляй комментарии, только укороченный текст.

Текст: {text}""",

    EditAction.IMPROVE: """Улучши этот текст: сделай его более ясным, убедительным и приятным для чтения. 
Улучши структуру предложений, подбери более точные слова, но сохрани оригинальный смысл и тон. Не добавляй комментарии, только улучшенный текст.

Текст: {text}""",

    EditAction.FORMAL: """Перепиши этот текст в формальном деловом стиле. 
Используй профессиональную лексику, сложные предложения, избегай разговорных выражений. 
Подходит для официальных писем, документов, отчетов. Не добавляй комментарии, только деловой текст.

Текст: {text}""",

    EditAction.FRIENDLY: """Перепиши этот текст в дружеском, неформальном стиле. 
Используй разговорные выражения, эмодзи (где уместно), сделай текст теплым и позитивным. 
Подходит для соцсетей, личных сообщений, блогов. Не добавляй комментарии, только дружеский текст.

Текст: {text}""",

    EditAction.REPHRASE: """Перефразируй этот текст, сказав то же самое другими словами. 
Измени структуру предложений, используй синонимы, но сохрани точный смысл оригинала. Не добавляй комментарии, только перефразированный текст.

Текст: {text}""",

    EditAction.CONTINUE: """Продолжи этот текст логически и стилистически. 
Добавь 2-3 предложения в конец, которые естественно продолжают мысль. Не добавляй комментарии,только исходный текст + его продолжение.

Текст: {text}"""
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
✏️ TextCraft AI — ваш личный редактор текстов!

Доступные действия:
• ✏️ Исправить — орфография, пунктуация, грамматика
• ✂️ Сократить — убрать воду, оставить суть
• 🚀 Улучшить — сделать текст убедительнее и яснее
• 🔄 Перефразировать — сказать то же самое другими словами
• 🎩 Формальный — деловой стиль для документов
• 😊 Дружеский — неформальный стиль для соцсетей
• ➡️ Продолжить текст — AI допишет текст за вас

💡Команды:
/edit - начать редактирование
/help - помощь
    """
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🆘 Помощь

📝 Как использовать:
1. Отправьте /edit чтобы начать
2. Выберите действие
3. Отправьте текст
4. Получите результат!

Ограничения:
• Максимальная длина текста: ~2000 символов
• Сохранение контекста: только в течение одной сессии
    """
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def start_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = user_sessions.get(user_id)

    if not user_data or not user_data.current_text:
        await update.message.reply_text(
            "📝 *Отправьте текст:*",
            parse_mode=ParseMode.MARKDOWN
        )
        return EDITING_TEXT
    else:
        await update.message.reply_text(
            f"📋 *Текущий текст:*\n\n{user_data.current_text[:300]}{'...' if len(user_data.current_text) > 300 else ''}\n\n*Выберите действие:*",
            reply_markup=get_main_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return SELECTING_ACTION


async def receive_initial_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if len(text) < 5:
        await update.message.reply_text("⚠️ Текст слишком короткий!")
        return EDITING_TEXT

    if len(text) > 2000:
        await update.message.reply_text("⚠️ Текст слишком длинный!")
        return EDITING_TEXT

    user_sessions[user_id] = UserData(current_text=text)

    await update.message.reply_text(
        f"✅ *Текст сохранен*\n\n*Выберите действие:*",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    return SELECTING_ACTION


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    data = query.data

    if data == "cancel":
        await query.edit_message_text("❌ Отменено")
        if user_id in user_sessions:
            del user_sessions[user_id]
        return ConversationHandler.END

    if user_id not in user_sessions:
        await query.edit_message_text("❌ Сессия устарела. /edit")
        return ConversationHandler.END

    user_data = user_sessions[user_id]

    try:
        action = EditAction(data)

        await query.edit_message_text("⏳ Обработка...")
        await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.TYPING)

        prompt = PROMPTS[action].format(text=user_data.current_text)
        response = client.chat.complete(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.7,
        )

        result = response.choices[0].message.content

        user_data.history.append({
            'action': action.value,
            'original': user_data.current_text,
            'result': result
        })

        user_data.current_text = result

        emoji_map = {
            EditAction.FIX: "✏️",
            EditAction.SHORTEN: "✂️",
            EditAction.IMPROVE: "🚀",
            EditAction.FORMAL: "🎩",
            EditAction.FRIENDLY: "😊",
            EditAction.REPHRASE: "🔄",
            EditAction.CONTINUE: "➡️",
        }

        await query.edit_message_text(
            f"{emoji_map[action]} *{action.name.upper()}*\n\n{result}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_after_edit_keyboard()
        )

        return EDITING_TEXT

    except ValueError:
        if data == "edit_more":
            await query.edit_message_text(
                f"📝 *Редактирование текста:*\n\n{user_data.current_text[:400]}{'...' if len(user_data.current_text) > 400 else ''}\n\n*Выберите действие:*",
                reply_markup=get_main_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            return SELECTING_ACTION

        elif data == "done":
            final_text = user_data.current_text

            await query.edit_message_text(
                "✅ *Редактирование завершено!*",
                parse_mode=ParseMode.MARKDOWN
            )

            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"📋 *ИТОГОВЫЙ ТЕКСТ*\n\n{final_text}",
                parse_mode=ParseMode.MARKDOWN
            )

            if user_data.history:
                actions = [h['action'] for h in user_data.history]
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"📊 *Статистика:*\n• Редактирований: {len(user_data.history)}\n• Действия: {', '.join(actions)}",
                    parse_mode=ParseMode.MARKDOWN
                )


            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="✏️ *TextCraft AI*\n\nОтправьте /edit чтобы начать",
                parse_mode=ParseMode.MARKDOWN
            )
            if user_id in user_sessions:
                del user_sessions[user_id]
            return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]

    await update.message.reply_text("❌ Отменено")
    return ConversationHandler.END


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("⚠️ Ошибка")


def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('edit', start_edit)],
        states={
            EDITING_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_initial_text),
                CallbackQueryHandler(button_handler),
            ],
            SELECTING_ACTION: [
                CallbackQueryHandler(button_handler),
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('start', start),
            CommandHandler('help', help_command),
        ],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    logger.info("🤖 Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':

    main()
