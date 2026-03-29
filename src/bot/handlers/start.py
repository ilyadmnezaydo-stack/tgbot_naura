"""
Start and help handlers for the keyboard-based bot UX.
"""
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from src.bot.keyboards import (
    BUTTON_ADD_CONTACT,
    BUTTON_HELP,
    BUTTON_LIST_CONTACTS,
    BUTTON_NOTES,
    BUTTON_OWNER_DASHBOARD,
    BUTTON_SEARCH_CONTACTS,
    BUTTON_SUPPORT,
    get_help_inline_keyboard,
    get_main_reply_keyboard,
    is_owner_user,
)
from src.services.analytics_service import record_interaction


WELCOME_TEXT = f"""<b>Личный CRM для тёплых связей</b>

Я помогаю держать в поле зрения людей, которые важны:
• сохраняю контакт и контекст
• напоминаю с удобной частотой
• помогаю быстро зафиксировать, что контакт уже был
• сохраняю короткие итоги общения

<b>Можно начать прямо сейчас</b>
• нажать «{BUTTON_ADD_CONTACT}»
• отправить <code>@username</code> или <code>@username короткий контекст</code>
• переслать сообщение человека

<b>Навигация уже внизу</b>
Кнопки собраны по сценариям, поэтому почти всё можно делать без команд."""


def build_help_text(user_id: int | None) -> str:
    """Build help text with optional owner-only sections."""
    lines = [
        "<b>Как устроен бот</b>",
        "",
        "<b>Быстрый старт</b>",
        f"• «{BUTTON_ADD_CONTACT}» — добавить человека вручную",
        "• переслать сообщение человека — импортировать контакт в 2 шага",
        f"• «{BUTTON_SEARCH_CONTACTS}» — найти по смыслу, тегам или имени",
        "",
        "<b>Главные разделы</b>",
        f"• «{BUTTON_LIST_CONTACTS}» — список карточек и быстрый вход в действия",
        f"• «{BUTTON_NOTES}» — заметки после общения и личная память по контактам",
        f"• «{BUTTON_HELP}» — краткая помощь по сценариям",
        f"• «{BUTTON_SUPPORT}» — поддержать развитие проекта",
        "",
        "<b>Что можно делать в карточке</b>",
        "• открыть редактирование и поправить контекст",
        "• добавить заметку после общения",
        "• поменять частоту напоминаний, поставить паузу или удалить карточку",
        "",
        "<b>Где управлять частотой напоминаний</b>",
        "Частота напоминаний настраивается при создании контакта и потом меняется прямо в карточке.",
        "",
        "<b>Полезный формат</b>",
        "<code>@username</code>",
        "<code>@username коллега из продуктовой команды</code>",
        "",
        "<b>Если нужен человек</b>",
        "Под этим сообщением есть кнопка <b>«Поддержка»</b>: сначала ответит AI, а сложный вопрос уйдёт админу.",
    ]

    if is_owner_user(user_id):
        lines.extend(
            [
                "",
                "<b>Для владельца</b>",
                f"• «{BUTTON_OWNER_DASHBOARD}» — быстрый вход в аналитику и общую статистику бота",
            ]
        )

    return "\n".join(lines)


REMINDERS_TEXT = """<b>Как работает частота напоминаний</b>

• можно выбрать регулярную частоту напоминаний или разовую дату
• утром бот присылает тех, кому пора написать
• вечером мягко повторяет напоминание, если контакт ещё не отмечен
• после отметки связи следующая дата считается автоматически
• частоту напоминаний можно поменять прямо из карточки"""


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the welcome text and the persistent keyboard."""
    await record_interaction(update.effective_user.id)
    await update.message.reply_text(
        WELCOME_TEXT,
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard(update.effective_user.id),
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Re-show the main navigation keyboard."""
    await update.message.reply_text(
        "Клавиатура перед тобой. Выбери нужный сценарий и продолжим.",
        reply_markup=get_main_reply_keyboard(update.effective_user.id),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explain the main flows without relying on slash commands."""
    await update.message.reply_text(
        build_help_text(update.effective_user.id),
        parse_mode="HTML",
        reply_markup=get_help_inline_keyboard(),
    )


async def reminders_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explain how reminders work in the bot."""
    await update.message.reply_text(
        REMINDERS_TEXT,
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard(update.effective_user.id),
    )


def get_start_handlers() -> list:
    """Return only the technical /start handler required by Telegram."""
    return [
        CommandHandler("start", start_command),
    ]
