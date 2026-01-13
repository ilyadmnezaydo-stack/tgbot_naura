"""
Handler for forwarded messages.
Extracts username from forwarded message and prompts user for description.
"""
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from src.bot.keyboards import get_confirm_contact_keyboard, get_existing_contact_keyboard
from src.bot.messages import format_contact_preview, format_description_prompt, format_existing_contact_found


async def handle_forwarded_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle forwarded messages to extract username.

    When user forwards a message from someone, we extract their username
    and prompt the user to provide a description for the contact.
    """
    message = update.message

    # Check if message has forward info
    if not message.forward_origin:
        return

    username = None
    first_name = None

    # Try to extract username from forward origin
    # python-telegram-bot v20+ uses forward_origin
    origin = message.forward_origin

    # Check origin type
    if hasattr(origin, "sender_user") and origin.sender_user:
        # MessageOriginUser - forwarded from a user
        sender = origin.sender_user
        username = sender.username
        first_name = sender.first_name or sender.username or "Unknown"
    elif hasattr(origin, "chat") and origin.chat:
        # MessageOriginChat - forwarded from a chat/channel
        chat = origin.chat
        username = chat.username
        first_name = chat.title or chat.username or "Unknown"

    if not username:
        await update.message.reply_text(
            "Не удалось определить username отправителя.\n"
            "Возможно, у пользователя скрыт профиль или это анонимное сообщение.\n\n"
            "Добавь контакт вручную через /add",
            parse_mode="Markdown",
        )
        return

    # Check if contact already exists
    from src.db.engine import get_session
    from src.db.repositories.contacts import ContactRepository

    user_id = update.effective_user.id

    async with get_session() as session:
        contact_repo = ContactRepository(session)
        existing = await contact_repo.get_by_username(user_id, username)

        if existing:
            # Show existing contact with update options
            await update.message.reply_text(
                format_existing_contact_found(username),
                parse_mode="Markdown",
                reply_markup=get_existing_contact_keyboard(str(existing.id)),
            )
            return

    # Store pending contact info in user_data for follow-up
    context.user_data["pending_contact"] = {
        "username": username.lower(),
        "first_name": first_name,
    }

    await update.message.reply_text(
        format_description_prompt(username, first_name),
        parse_mode="Markdown",
    )


async def handle_pending_contact_description(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Handle description input after forwarded message.
    Uses LLM to parse description and tags.
    Shows preview with confirmation buttons.

    Returns True if there was a pending contact and it was processed.
    """
    from src.services.ai_service import AIService

    pending = context.user_data.get("pending_contact")
    if not pending:
        return False

    text = update.message.text

    # Check for cancel
    if text.lower() in ["/cancel", "отмена", "cancel"]:
        del context.user_data["pending_contact"]
        await update.message.reply_text("Отменено.")
        return True

    username = pending["username"]

    # Parse input using LLM (description, tags only - no frequency here)
    ai_service = AIService()
    parsed = await ai_service.parse_contact_input(text)

    if not parsed:
        # Fallback to simple mode
        description = text
        tags = []
    else:
        description = parsed.description
        tags = parsed.tags

    # Store draft contact for confirmation
    context.user_data["draft_contact"] = {
        "username": username,
        "description": description,
        "tags": tags,
    }

    # Clear pending, keep draft
    del context.user_data["pending_contact"]

    # Show preview with confirmation buttons
    await update.message.reply_text(
        format_contact_preview(username, description, tags),
        parse_mode="Markdown",
        reply_markup=get_confirm_contact_keyboard(),
    )

    return True


def get_forwarded_handler():
    """Return forwarded message handler"""
    return MessageHandler(
        filters.FORWARDED & ~filters.COMMAND,
        handle_forwarded_message,
    )
