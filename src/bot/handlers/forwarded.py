"""
Handler for forwarded messages.
Extracts username from a forwarded message and prepares contact creation.
"""
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from src.bot.input_text import get_input_text
from src.bot.keyboards import (
    BUTTON_CANCEL_ACTION,
    get_confirm_contact_keyboard,
    get_existing_contact_keyboard,
    get_optional_context_keyboard,
)
from src.bot.messages import (
    format_contact_preview,
    format_description_prompt,
    format_existing_contact_found,
    format_optional_context_prompt,
)
from src.services.analytics_service import record_interaction
from src.services.contact_enrichment import enrich_contact_data


async def handle_forwarded_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle forwarded messages and try to extract the sender username."""
    await record_interaction(update.effective_user.id)
    message = update.message

    if not message.forward_origin:
        return

    username = None
    display_name = None
    origin = message.forward_origin

    if hasattr(origin, "sender_user") and origin.sender_user:
        sender = origin.sender_user
        username = sender.username
        display_name = sender.first_name or ""
        if sender.last_name:
            display_name = f"{display_name} {sender.last_name}".strip()
        if not display_name:
            display_name = sender.username or "Unknown"
    elif hasattr(origin, "sender_user_name"):
        display_name = origin.sender_user_name
    elif hasattr(origin, "chat") and origin.chat:
        chat = origin.chat
        username = chat.username
        display_name = chat.title or chat.username or "Unknown"

    if not username:
        await update.message.reply_text(
            "Не удалось определить username отправителя.\n"
            "Возможно, профиль скрыт или сообщение было отправлено анонимно.\n\n"
            "Если хочешь, добавь контакт вручную через кнопку «✨ Добавить».",
            parse_mode="HTML",
        )
        return

    from src.db.engine import get_supabase
    from src.db.repositories.contacts import ContactRepository

    user_id = update.effective_user.id
    client = await get_supabase()
    contact_repo = ContactRepository(client)
    existing = await contact_repo.get_by_username(user_id, username)

    if existing:
        await update.message.reply_text(
            format_existing_contact_found(username),
            parse_mode="HTML",
            reply_markup=get_existing_contact_keyboard(str(existing.id)),
        )
        return

    context.user_data["pending_contact"] = {
        "username": username.lower(),
        "display_name": display_name,
        "source": "forwarded",
    }

    await update.message.reply_text(
        format_description_prompt(username, display_name),
        parse_mode="HTML",
    )


async def handle_pending_contact_description(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Handle description input after a forwarded message.
    Returns True if there was a pending contact flow and it was processed.
    """
    pending = context.user_data.get("pending_contact")
    if not pending:
        return False

    text = get_input_text(update, context)
    if not text:
        return True

    if text.lower() in ["/cancel", "отмена", "cancel", BUTTON_CANCEL_ACTION.lower()]:
        del context.user_data["pending_contact"]
        await update.message.reply_text("Шаг отменён. Можно выбрать другой сценарий.")
        return True

    username = pending["username"]
    display_name = pending.get("display_name")
    source = pending.get("source", "forwarded")

    if pending.get("awaiting_context_choice"):
        await update.message.reply_text(
            format_optional_context_prompt(username, display_name),
            parse_mode="HTML",
            reply_markup=get_optional_context_keyboard(),
        )
        return True

    pending["awaiting_context_choice"] = False

    enriched = await enrich_contact_data(
        username=username,
        raw_description=text,
        suggested_display_name=display_name,
    )

    context.user_data["draft_contact"] = {
        "username": username,
        "display_name": enriched.display_name or display_name,
        "description": enriched.description,
        "tags": enriched.tags,
        "birthday_day": enriched.birthday_day,
        "birthday_month": enriched.birthday_month,
        "birthday_year": enriched.birthday_year,
        "source": source,
    }
    del context.user_data["pending_contact"]

    await update.message.reply_text(
        format_contact_preview(
            username,
            enriched.description,
            enriched.tags,
            enriched.display_name or display_name,
            birthday_day=enriched.birthday_day,
            birthday_month=enriched.birthday_month,
            birthday_year=enriched.birthday_year,
        ),
        parse_mode="HTML",
        reply_markup=get_confirm_contact_keyboard(),
    )

    return True


def get_forwarded_handler():
    """Return the forwarded-message handler."""
    return MessageHandler(
        filters.FORWARDED & ~filters.COMMAND,
        handle_forwarded_message,
    )
