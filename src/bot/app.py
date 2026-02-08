"""
Telegram Application setup and message routing.
"""
import logging
import re
from datetime import date, timedelta
from uuid import UUID

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from src.bot.handlers.callbacks import get_callback_handler, send_contact_card
from src.bot.handlers.contacts import (
    get_contact_handlers,
    handle_add_from_prompt,
    handle_edit_from_prompt,
)
from src.bot.handlers.forwarded import (
    get_forwarded_handler,
    handle_pending_contact_description,
)
from src.bot.handlers.search import perform_search
from src.bot.handlers.start import get_start_handlers
from src.bot.keyboards import get_confirm_add_username_keyboard
from src.bot.messages import format_reminder_set
from src.bot.parsers.frequency import format_frequency, parse_date
from src.config import settings
from src.db.engine import get_supabase
from src.db.repositories.contacts import ContactRepository
from src.scheduler.setup import setup_scheduler

# Regex for extracting Telegram username from text
USERNAME_REGEX = re.compile(r"@([a-zA-Z][a-zA-Z0-9_]{4,31})")

logger = logging.getLogger(__name__)


def extract_username(text: str) -> str | None:
    """Extract first Telegram username from text (without @)."""
    match = USERNAME_REGEX.search(text)
    return match.group(1) if match else None


async def check_and_offer_username_contact(update: Update, context, text: str) -> bool:
    """
    Check if message contains @username and offer to add as contact.
    Returns True if username was found and offer was made, False otherwise.
    """
    username = extract_username(text)
    if not username:
        return False

    user_id = update.effective_user.id

    # Check if contact already exists
    client = await get_supabase()
    repo = ContactRepository(client)
    existing = await repo.get_by_username(user_id, username)

    if existing:
        await update.message.reply_text(
            f"Контакт @{username} уже существует в твоём списке."
        )
        return True

    # Offer to add the contact
    await update.message.reply_text(
        f"Хочешь добавить @{username} как контакт?",
        reply_markup=get_confirm_add_username_keyboard(username),
    )
    return True


async def route_message(update: Update, context) -> None:
    """
    Main message router for text messages.
    Handles pending operations (add, search, edit, custom interval/date).
    """
    text = update.message.text
    if not text:
        return

    # 1. Check for pending contact from forwarded message
    if await handle_pending_contact_description(update, context):
        return

    # 2. Check for awaiting custom interval input
    if context.user_data.get("awaiting_custom_interval"):
        await handle_custom_interval_input(update, context)
        return

    # 3. Check for awaiting custom date input
    if context.user_data.get("awaiting_custom_date"):
        await handle_custom_date_input(update, context)
        return

    # 4. Check for awaiting_add (after /add or button press)
    if context.user_data.get("awaiting_add"):
        await handle_add_from_prompt(update, context)
        return

    # 5. Check for awaiting_search (after /search)
    if context.user_data.get("awaiting_search"):
        context.user_data.pop("awaiting_search", None)
        await perform_search(update, context, text)
        return

    # 6. Check for editing_contact (after /edit or ✏️ button)
    if context.user_data.get("editing_contact"):
        await handle_edit_from_prompt(update, context)
        return

    # 7. Check for @username in message and offer to add as contact
    if await check_and_offer_username_contact(update, context, text):
        return

    # 8. Unknown message - show help
    await update.message.reply_text(
        "Используй команды:\n"
        "/add — добавить контакт\n"
        "/list — список контактов\n"
        "/search — поиск\n"
        "/help — справка"
    )


async def handle_custom_interval_input(update: Update, context) -> None:
    """Handle custom interval input (number of days)."""
    text = update.message.text.strip()
    contact_id = context.user_data.get("awaiting_custom_interval")

    # Clear the flag
    del context.user_data["awaiting_custom_interval"]

    # Validate input
    try:
        days = int(text)
        if days < 1 or days > 365:
            raise ValueError("Out of range")
    except ValueError:
        await update.message.reply_text(
            "Введи число от 1 до 365.\n"
            "Например: <code>45</code>",
            parse_mode="HTML",
        )
        context.user_data["awaiting_custom_interval"] = contact_id
        return

    next_date = date.today() + timedelta(days=days)

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if contact:
        await repo.update(
            contact.id,
            reminder_frequency="custom",
            custom_interval_days=days,
            next_reminder_date=next_date,
            status="active",
        )

        freq_text = format_frequency("custom", days)
        await update.message.reply_text(
            format_reminder_set(contact.username, freq_text, next_date.strftime("%d.%m.%Y")),
            parse_mode="HTML",
        )
        await send_contact_card(update.message, await repo.get_by_id(UUID(contact_id)))


async def handle_custom_date_input(update: Update, context) -> None:
    """Handle custom date input for one-time reminder using AI parsing."""
    from src.services.ai_service import AIService

    text = update.message.text.strip()
    contact_id = context.user_data.get("awaiting_custom_date")

    # Clear the flag
    del context.user_data["awaiting_custom_date"]

    # First try simple regex parsing
    reminder_date = parse_date(text)

    # If simple parsing failed, try AI
    if not reminder_date:
        ai_service = AIService()
        reminder_date = await ai_service.parse_date(text)

    if not reminder_date:
        await update.message.reply_text(
            "Не удалось распознать дату.\n\n"
            "Попробуй написать иначе:\n"
            "• <code>завтра</code>\n"
            "• <code>через неделю</code>\n"
            "• <code>15 февраля</code>\n"
            "• <code>в пятницу</code>\n"
            "• <code>25.02.2025</code>",
            parse_mode="HTML",
        )
        context.user_data["awaiting_custom_date"] = contact_id
        return

    if reminder_date <= date.today():
        await update.message.reply_text(
            "Дата должна быть в будущем.\n"
            "Введи другую дату:",
            parse_mode="HTML",
        )
        context.user_data["awaiting_custom_date"] = contact_id
        return

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if contact:
        await repo.update(
            contact.id,
            reminder_frequency="one_time",
            next_reminder_date=reminder_date,
            one_time_date=reminder_date,
            status="one_time",
        )

        await update.message.reply_text(
            format_reminder_set(contact.username, "однократно", reminder_date.strftime("%d.%m.%Y")),
            parse_mode="HTML",
        )
        await send_contact_card(update.message, await repo.get_by_id(UUID(contact_id)))


async def cancel_command(update: Update, context) -> None:
    """Handle /cancel command - cancel pending operations"""
    cancelled = False

    keys_to_clear = [
        "pending_contact",
        "draft_contact",
        "awaiting_add",
        "awaiting_search",
        "editing_contact",
        "awaiting_custom_interval",
        "awaiting_custom_date",
        "setting_reminder_for",
    ]

    for key in keys_to_clear:
        if key in context.user_data:
            del context.user_data[key]
            cancelled = True

    if cancelled:
        await update.message.reply_text("Операция отменена.")
    else:
        await update.message.reply_text("Нечего отменять.")


def create_application() -> Application:
    """
    Create and configure the Telegram bot application.
    """
    logger.info("Creating Telegram application...")

    # Build application
    application = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Add /start and /help handlers
    for handler in get_start_handlers():
        application.add_handler(handler)

    # Add /list handler
    for handler in get_contact_handlers():
        application.add_handler(handler)

    # Add /cancel handler
    application.add_handler(CommandHandler("cancel", cancel_command))

    # Add callback query handler (for inline buttons)
    application.add_handler(get_callback_handler())

    # Add forwarded message handler (before text message handler)
    application.add_handler(get_forwarded_handler())

    # Add main text message router (catches all text messages)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            route_message,
        )
    )

    # Setup scheduled jobs
    setup_scheduler(application)

    logger.info("Application configured successfully")

    return application
