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

<b>Как это работает:</b>
1️⃣ Добавь контакт с описанием
2️⃣ Я напомню, когда пора написать
3️⃣ Отметь, что связался — и счётчик обновится

Выбери действие:"""

    await update.message.reply_text(
        welcome_text,
        parse_mode="HTML",
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
    help_text = """<b>Команды</b>

/add — добавить контакт
/list — список контактов
/search — поиск по контактам
/edit @username — редактировать
/cancel — отменить операцию

<b>Добавление контакта</b>
1. Нажми /add
2. Отправь: <code>@username описание. частота</code>

Примеры:
• <code>@anna маркетолог. раз в неделю</code>
• <code>@ivan друг из универа. раз в месяц</code>
• <code>@lena инвестор</code>

💡 Без частоты — напомню раз в 2 недели.

<b>Кнопки у контактов</b>
✅ — отметить, что связался
✏️ — изменить описание/частоту
⏸️ — приостановить напоминания
▶️ — возобновить
❌ — удалить

<b>Поиск</b>
/search → введи запрос
• <code>кто работает в IT?</code>
• <code>друзья из Москвы</code>

<b>Пересланные сообщения</b>
Перешли сообщение от человека → я предложу добавить его в контакты.

<b>Напоминания</b>
• 11:00 — утреннее
• 19:00 — вечернее (если не отметил)
• Воскресенье — статистика за неделю

<b>Частоты</b>
• <code>ежедневно</code> / <code>каждый день</code>
• <code>раз в неделю</code>
• <code>раз в 2 недели</code> (по умолчанию)
• <code>раз в месяц</code>
• <code>через X дней</code>
• Дата: <code>15.01.2025</code>"""

    await update.message.reply_text(help_text, parse_mode="HTML")


def get_start_handlers() -> list:
    """Return list of start/help/menu handlers"""
    return [
        CommandHandler("start", start_command),
        CommandHandler("help", help_command),
        CommandHandler("menu", menu_command),
    ]
