"""
Telegram Application setup and message routing.
"""
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from src.bot.handlers.callbacks import get_callback_handler
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
from src.config import settings
from src.scheduler.setup import setup_scheduler

logger = logging.getLogger(__name__)


async def route_message(update: Update, context) -> None:
    """
    Main message router for text messages.
    Handles pending operations (add, search, edit).
    """
    text = update.message.text
    if not text:
        return

    # 1. Check for pending contact from forwarded message
    if await handle_pending_contact_description(update, context):
        return

    # 2. Check for awaiting_add (after /add or button press)
    if context.user_data.get("awaiting_add"):
        await handle_add_from_prompt(update, context)
        return

    # 3. Check for awaiting_search (after /search)
    if context.user_data.get("awaiting_search"):
        context.user_data.pop("awaiting_search", None)
        await perform_search(update, context, text)
        return

    # 4. Check for editing_contact (after /edit or ✏️ button)
    if context.user_data.get("editing_contact"):
        await handle_edit_from_prompt(update, context)
        return

    # 5. Unknown message - show help
    await update.message.reply_text(
        "Используй команды:\n"
        "/add — добавить контакт\n"
        "/list — список контактов\n"
        "/search — поиск\n"
        "/help — справка"
    )


async def cancel_command(update: Update, context) -> None:
    """Handle /cancel command - cancel pending operations"""
    cancelled = False

    if "pending_contact" in context.user_data:
        del context.user_data["pending_contact"]
        cancelled = True

    if "awaiting_add" in context.user_data:
        del context.user_data["awaiting_add"]
        cancelled = True

    if "awaiting_search" in context.user_data:
        del context.user_data["awaiting_search"]
        cancelled = True

    if "editing_contact" in context.user_data:
        del context.user_data["editing_contact"]
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
