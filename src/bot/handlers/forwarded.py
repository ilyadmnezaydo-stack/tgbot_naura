"""
Handler for forwarded messages.
Extracts username from forwarded message and prompts user for description.
"""
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters


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
    from src.bot.handlers.callbacks import send_contact_card
    from src.db.engine import get_session
    from src.db.repositories.contacts import ContactRepository

    user_id = update.effective_user.id

    async with get_session() as session:
        contact_repo = ContactRepository(session)
        existing = await contact_repo.get_by_username(user_id, username)

        if existing:
            await update.message.reply_text(
                f"📇 *@{username}* уже в твоих контактах:",
                parse_mode="Markdown",
            )
            await send_contact_card(update.message, existing)
            return

    # Store pending contact info in user_data for follow-up
    context.user_data["pending_contact"] = {
        "username": username.lower(),
        "first_name": first_name,
    }

    await update.message.reply_text(
        f"📇 Добавить *@{username}* в контакты?\n\n"
        f"Напиши описание:\n"
        f"`{first_name} — коллега из IT. раз в неделю`\n\n"
        f"Или /cancel для отмены.",
        parse_mode="Markdown",
    )


async def handle_pending_contact_description(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Handle description input after forwarded message.

    Returns True if there was a pending contact and it was processed.
    """
    pending = context.user_data.get("pending_contact")
    if not pending:
        return False

    text = update.message.text

    # Check for cancel
    if text.lower() in ["/cancel", "отмена", "cancel"]:
        del context.user_data["pending_contact"]
        await update.message.reply_text("Отменено.")
        return True

    # Parse the description - just add the contact with provided description
    username = pending["username"]
    description = text

    # Clear pending
    del context.user_data["pending_contact"]

    # Import here to avoid circular imports
    from src.bot.parsers.frequency import calculate_next_reminder, parse_frequency
    from src.db.engine import get_session
    from src.db.repositories.contacts import ContactRepository
    from src.db.repositories.users import UserRepository
    from src.services.ai_service import AIService

    user_id = update.effective_user.id

    # Try to extract frequency from the description
    frequency = "biweekly"
    custom_days = None

    # Check if text contains frequency info (after a period)
    if ". " in text:
        parts = text.rsplit(". ", 1)
        description = parts[0]
        freq_text = parts[1] if len(parts) > 1 else ""
        freq_result = parse_frequency(freq_text)
        if freq_result:
            frequency, custom_days = freq_result

    async with get_session() as session:
        # Ensure user exists
        user_repo = UserRepository(session)
        await user_repo.get_or_create(
            user_id=user_id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
        )

        contact_repo = ContactRepository(session)

        # Check if contact already exists
        existing = await contact_repo.get_by_username(user_id, username)
        if existing:
            await update.message.reply_text(
                f"Контакт @{username} уже существует.\n"
                f"Используй `/edit @{username}` для редактирования.",
                parse_mode="Markdown",
            )
            return True

        # Extract tags using AI
        ai_service = AIService()
        tags = await ai_service.extract_tags(description)

        # Calculate next reminder
        next_reminder = calculate_next_reminder(frequency, custom_days)

        # Create contact
        contact = await contact_repo.create(
            user_id=user_id,
            username=username,
            description=description,
            tags=tags,
            reminder_frequency=frequency,
            custom_interval_days=custom_days,
            next_reminder_date=next_reminder,
            status="active",
        )

        # Format response
        from src.bot.parsers.frequency import format_frequency

        freq_text = format_frequency(frequency, custom_days)
        tags_text = " ".join(tags) if tags else "—"

        await update.message.reply_text(
            f"✅ Контакт добавлен!\n\n"
            f"*@{username}*\n"
            f"{description}\n\n"
            f"Теги: {tags_text}\n"
            f"Напоминание: {freq_text}\n"
            f"Следующее: {next_reminder.strftime('%d.%m.%Y')}",
            parse_mode="Markdown",
        )

    return True


def get_forwarded_handler():
    """Return forwarded message handler"""
    return MessageHandler(
        filters.FORWARDED & ~filters.COMMAND,
        handle_forwarded_message,
    )
