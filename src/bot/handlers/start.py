"""
Start and help command handlers.
"""
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from src.bot.handlers.callbacks import get_main_menu_keyboard


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command - welcome message with menu"""
    welcome_text = """Привет! 👋

Я помогу тебе не терять связь с важными людьми.

*Как это работает:*
1️⃣ Добавь контакт с описанием
2️⃣ Я напомню, когда пора написать
3️⃣ Отметь, что связался — и счётчик обновится

Выбери действие:"""

    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard(),
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /menu command - show main menu"""
    await update.message.reply_text(
        "Выбери действие:",
        reply_markup=get_main_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command - full help message"""
    help_text = """*Команды*

/add — добавить контакт
/list — список контактов
/search — поиск по контактам
/edit @username — редактировать
/cancel — отменить операцию

*Добавление контакта*
1. Нажми /add
2. Отправь: `@username описание. частота`

Примеры:
• `@anna маркетолог. раз в неделю`
• `@ivan друг из универа. раз в месяц`
• `@lena инвестор`

💡 Без частоты — напомню раз в 2 недели.

*Кнопки у контактов*
✅ — отметить, что связался
✏️ — изменить описание/частоту
⏸️ — приостановить напоминания
▶️ — возобновить
❌ — удалить

*Поиск*
/search → введи запрос
• `кто работает в IT?`
• `друзья из Москвы`

*Пересланные сообщения*
Перешли сообщение от человека → я предложу добавить его в контакты.

*Напоминания*
• 11:00 — утреннее
• 19:00 — вечернее (если не отметил)
• Воскресенье — статистика за неделю

*Частоты*
• `ежедневно` / `каждый день`
• `раз в неделю`
• `раз в 2 недели` (по умолчанию)
• `раз в месяц`
• `через X дней`
• Дата: `15.01.2025`"""

    await update.message.reply_text(help_text, parse_mode="Markdown")


def get_start_handlers() -> list:
    """Return list of start/help/menu handlers"""
    return [
        CommandHandler("start", start_command),
        CommandHandler("help", help_command),
        CommandHandler("menu", menu_command),
    ]
