"""
Contact management handlers: add, update, list.
"""
import re
from datetime import date

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
from telegram.helpers import escape_markdown

from src.bot.handlers.callbacks import get_main_menu_keyboard, send_contact_card
from src.bot.parsers.frequency import calculate_next_reminder, format_frequency
from src.db.engine import get_session
from src.db.repositories.contacts import ContactRepository
from src.db.repositories.users import UserRepository
from src.services.ai_service import AIService

# Simple pattern to extract @username from the beginning
USERNAME_PATTERN = re.compile(
    r"^@?([a-zA-Z][a-zA-Z0-9_]{4,31})\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)


async def handle_add_from_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Handle add contact after /add command or button press.
    Uses LLM to parse description, tags, and frequency.

    Returns True if handled, False otherwise.
    """
    text = update.message.text.strip()

    # Extract username
    match = USERNAME_PATTERN.match(text)
    if not match:
        await update.message.reply_text(
            "Не удалось распознать формат.\n\n"
            "Отправь в формате:\n"
            "`@username описание контакта`\n\n"
            "Например:\n"
            "`@ivan коллега из маркетинга. раз в неделю`\n"
            "`@anna друг. напомни завтра`",
            parse_mode="Markdown",
        )
        return True

    username = match.group(1)
    raw_description = match.group(2).strip()

    # Clear the awaiting flag
    context.user_data.pop("awaiting_add", None)

    user_id = update.effective_user.id

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
            safe_username = escape_markdown(username, version=1)
            await update.message.reply_text(
                f"Контакт @{safe_username} уже существует.\n"
                f"Используй `/edit @{safe_username}` для редактирования.",
                parse_mode="Markdown",
            )
            return True

        # Parse input using LLM (description, tags, frequency, date)
        ai_service = AIService()
        parsed = await ai_service.parse_contact_input(raw_description)

        if not parsed:
            # Fallback to simple mode
            description = raw_description
            tags = []
            frequency = "biweekly"
            custom_days = None
            one_time_date = None
        else:
            description = parsed.description
            tags = parsed.tags
            frequency = parsed.frequency_type
            custom_days = parsed.custom_days
            one_time_date = None

            # Parse reminder_date if provided
            if parsed.reminder_date:
                try:
                    one_time_date = date.fromisoformat(parsed.reminder_date)
                except ValueError:
                    pass

        # Calculate next reminder date
        if frequency == "one_time" and one_time_date:
            next_reminder = one_time_date
            status = "one_time"
        else:
            next_reminder = calculate_next_reminder(frequency, custom_days)
            status = "active"

        # Create contact
        await contact_repo.create(
            user_id=user_id,
            username=username,
            description=description,
            tags=tags,
            reminder_frequency=frequency,
            custom_interval_days=custom_days,
            next_reminder_date=next_reminder,
            one_time_date=one_time_date,
            status=status,
        )

        # Format response
        freq_display = format_frequency(frequency, custom_days)
        tags_text = " ".join(tags) if tags else "—"

        # Escape markdown in user-provided text
        safe_desc = escape_markdown(description, version=1)
        safe_tags = escape_markdown(tags_text, version=1)
        safe_username = escape_markdown(username, version=1)

        await update.message.reply_text(
            f"✅ Контакт добавлен!\n\n"
            f"*@{safe_username}*\n"
            f"{safe_desc}\n\n"
            f"Теги: {safe_tags}\n"
            f"Напоминание: {freq_display}\n"
            f"Следующее: {next_reminder.strftime('%d.%m.%Y')}",
            parse_mode="Markdown",
        )

    return True


async def handle_list_contacts(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /list command - show all contacts with inline buttons"""
    user_id = update.effective_user.id

    async with get_session() as session:
        contact_repo = ContactRepository(session)
        contacts = await contact_repo.get_all_for_user(user_id)

        if not contacts:
            await update.message.reply_text(
                "У тебя пока нет контактов.\n"
                "Нажми *➕ Добавить контакт* чтобы добавить первый.",
                parse_mode="Markdown",
                reply_markup=get_main_menu_keyboard(),
            )
            return

        await update.message.reply_text(f"📋 *Твои контакты ({len(contacts)}):*", parse_mode="Markdown")

        # Send each contact as a separate message with buttons
        for contact in contacts:
            await send_contact_card(update.message, contact)


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /add command - prompt for contact details"""
    context.user_data["awaiting_add"] = True

    await update.message.reply_text(
        "➕ *Добавление контакта*\n\n"
        "Отправь данные в формате:\n"
        "`@username описание контакта. частота`\n\n"
        "Примеры:\n"
        "• `@ivan коллега из маркетинга. раз в неделю`\n"
        "• `@anna друг детства. раз в месяц`\n"
        "• `@peter партнер по бизнесу`\n\n"
        "💡 Если не указать частоту — напомню раз в 2 недели.",
        parse_mode="Markdown",
    )


async def handle_edit_from_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Handle edit input after /edit or button press.
    Uses LLM to parse and update only the requested fields.
    """
    from uuid import UUID

    contact_id_str = context.user_data.get("editing_contact")
    if not contact_id_str:
        return False

    text = update.message.text.strip()
    user_id = update.effective_user.id

    # Clear the editing flag
    context.user_data.pop("editing_contact", None)

    async with get_session() as session:
        contact_repo = ContactRepository(session)
        contact = await contact_repo.get_by_id(UUID(contact_id_str))

        if not contact or contact.user_id != user_id:
            await update.message.reply_text("Контакт не найден.")
            return True

        # Use LLM to parse edit request with current contact context
        ai_service = AIService()
        parsed = await ai_service.parse_contact_edit(
            edit_request=text,
            current_description=contact.description or "",
            current_tags=contact.tags or [],
            current_frequency=contact.reminder_frequency or "biweekly",
        )

        if not parsed:
            await update.message.reply_text("Не удалось определить, что обновить.")
            return True

        updates = {}
        response_parts = [f"✅ Контакт @{contact.username} обновлён:\n"]

        # Update description if requested
        if parsed.update_description and parsed.new_description:
            updates["description"] = parsed.new_description
            response_parts.append(f"Описание: {parsed.new_description}")

        # Update tags if requested
        if parsed.update_tags and parsed.new_tags is not None:
            updates["tags"] = parsed.new_tags
            tags_str = " ".join(parsed.new_tags) if parsed.new_tags else "—"
            response_parts.append(f"Теги: {tags_str}")

        # Update frequency if requested
        if parsed.update_frequency and parsed.new_frequency_type:
            updates["reminder_frequency"] = parsed.new_frequency_type
            updates["custom_interval_days"] = parsed.new_custom_days

            # Handle one-time reminder with date
            if parsed.new_frequency_type == "one_time" and parsed.new_reminder_date:
                try:
                    one_time_date = date.fromisoformat(parsed.new_reminder_date)
                    updates["next_reminder_date"] = one_time_date
                    updates["one_time_date"] = one_time_date
                    updates["status"] = "one_time"
                except ValueError:
                    pass
            else:
                new_next = calculate_next_reminder(parsed.new_frequency_type, parsed.new_custom_days)
                updates["next_reminder_date"] = new_next
                if contact.status == "one_time":
                    updates["status"] = "active"

            freq_text = format_frequency(parsed.new_frequency_type, parsed.new_custom_days)
            response_parts.append(f"Частота: {freq_text}")
            if "next_reminder_date" in updates:
                response_parts.append(f"Следующее: {updates['next_reminder_date'].strftime('%d.%m.%Y')}")

        if updates:
            await contact_repo.update(contact, **updates)
            await update.message.reply_text("\n".join(response_parts))
        else:
            await update.message.reply_text("Не удалось определить, что обновить.")

    return True


async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /edit command - prompt for contact to edit"""
    # Check if username provided: /edit @username
    if context.args:
        username = context.args[0].lstrip("@")
        user_id = update.effective_user.id

        async with get_session() as session:
            contact_repo = ContactRepository(session)
            contact = await contact_repo.get_by_username(user_id, username)

            if not contact:
                await update.message.reply_text(f"Контакт @{username} не найден.")
                return

            context.user_data["editing_contact"] = str(contact.id)

            # Escape markdown in user-provided text
            safe_desc = escape_markdown(contact.description, version=1) if contact.description else "не указано"
            safe_tags = escape_markdown(' '.join(contact.tags), version=1) if contact.tags else "—"
            safe_username = escape_markdown(username, version=1)

            await update.message.reply_text(
                f"✏️ *Редактирование @{safe_username}*\n\n"
                f"Текущее описание: _{safe_desc}_\n"
                f"Теги: {safe_tags}\n\n"
                "Отправь новые данные:\n"
                "• Новое описание\n"
                "• Или новую частоту (раз в неделю, раз в месяц...)\n"
                "• Или теги (#tag1 #tag2)\n\n"
                "Отправь `/cancel` для отмены.",
                parse_mode="Markdown",
            )
    else:
        await update.message.reply_text(
            "✏️ *Редактирование контакта*\n\n"
            "Используй: `/edit @username`\n\n"
            "Или нажми кнопку ✏️ у контакта в `/list`",
            parse_mode="Markdown",
        )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search command - prompt for search query"""
    # Check if query provided: /search query
    if context.args:
        query = " ".join(context.args)
        context.user_data["search_query"] = query
        # Trigger search handler
        from src.bot.handlers.search import perform_search
        await perform_search(update, context, query)
    else:
        context.user_data["awaiting_search"] = True

        await update.message.reply_text(
            "🔍 *Поиск контактов*\n\n"
            "Введи поисковый запрос:\n"
            "• `кто работает в IT?`\n"
            "• `контакты из Москвы`\n"
            "• `друзья`",
            parse_mode="Markdown",
        )


def get_contact_handlers() -> list:
    """Return list of contact handlers"""
    return [
        CommandHandler("list", handle_list_contacts),
        CommandHandler("add", add_command),
        CommandHandler("edit", edit_command),
        CommandHandler("search", search_command),
    ]
