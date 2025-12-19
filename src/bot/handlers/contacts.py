"""
Contact management handlers: add, update, list.
"""
import re

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from src.bot.handlers.callbacks import get_main_menu_keyboard, send_contact_card
from src.bot.parsers.frequency import calculate_next_reminder, format_frequency, parse_frequency, parse_date
from src.db.engine import get_session
from src.db.repositories.contacts import ContactRepository
from src.db.repositories.users import UserRepository
from src.services.ai_service import AIService

# Pattern for @username description. frequency (without "добавь")
DIRECT_ADD_PATTERN = re.compile(
    r"^@?([a-zA-Z][a-zA-Z0-9_]{4,31})\s+(.+?)(?:\.\s*(.+))?$",
    re.IGNORECASE | re.DOTALL,
)


async def handle_add_from_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Handle add contact after /add command or button press.
    Format: @username description. frequency (without "добавь" prefix)

    Returns True if handled, False otherwise.
    """
    text = update.message.text.strip()

    # Try to parse direct format: @username description. frequency
    match = DIRECT_ADD_PATTERN.match(text)
    if not match:
        await update.message.reply_text(
            "Не удалось распознать формат.\n\n"
            "Отправь в формате:\n"
            "`@username описание контакта. частота`\n\n"
            "Например:\n"
            "`@ivan коллега из маркетинга. раз в неделю`",
            parse_mode="Markdown",
        )
        return True

    username = match.group(1)
    description = match.group(2).strip()
    freq_text = match.group(3)

    # Parse frequency
    frequency = "biweekly"
    custom_days = None
    one_time_date = None

    if freq_text:
        freq_text = freq_text.strip()
        # Try parsing as frequency
        freq_result = parse_frequency(freq_text)
        if freq_result:
            frequency, custom_days = freq_result
            # If one_time, try to parse date
            if frequency == "one_time":
                parsed_date = parse_date(freq_text)
                if parsed_date:
                    one_time_date = parsed_date
        else:
            # Try parsing as date (one-time reminder)
            parsed_date = parse_date(freq_text)
            if parsed_date:
                frequency = "one_time"
                one_time_date = parsed_date

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
            await update.message.reply_text(
                f"Контакт @{username} уже существует.\n"
                f"Используй `/edit @{username}` для редактирования.",
                parse_mode="Markdown",
            )
            return True

        # Extract tags using AI
        ai_service = AIService()
        tags = await ai_service.extract_tags(description)

        # Calculate next reminder date
        if frequency == "one_time" and one_time_date:
            next_reminder = one_time_date
            status = "one_time"
        else:
            next_reminder = calculate_next_reminder(frequency, custom_days)
            status = "active"

        # Create contact
        contact = await contact_repo.create(
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

        await update.message.reply_text(
            f"✅ Контакт добавлен!\n\n"
            f"*@{username}*\n"
            f"{description}\n\n"
            f"Теги: {tags_text}\n"
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
    Updates description, tags, or frequency based on input.
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

        updates = {}
        response_parts = [f"✅ Контакт @{contact.username} обновлён:\n"]

        # Check if input is tags (starts with #)
        if text.startswith("#"):
            import re
            tags = re.findall(r"#(\w+)", text)
            tags = [f"#{t}" for t in tags]
            updates["tags"] = tags
            response_parts.append(f"Теги: {' '.join(tags)}")

        # Check if input is frequency
        else:
            freq_result = parse_frequency(text)
            if freq_result:
                frequency, custom_days = freq_result
                updates["reminder_frequency"] = frequency
                updates["custom_interval_days"] = custom_days

                # Recalculate next reminder
                new_next = calculate_next_reminder(frequency, custom_days)
                updates["next_reminder_date"] = new_next

                freq_text = format_frequency(frequency, custom_days)
                response_parts.append(f"Частота: {freq_text}")
                response_parts.append(f"Следующее: {new_next.strftime('%d.%m.%Y')}")
            else:
                # Treat as new description
                updates["description"] = text
                response_parts.append(f"Описание: {text}")

                # Re-extract tags from new description
                ai_service = AIService()
                new_tags = await ai_service.extract_tags(text)
                updates["tags"] = new_tags
                if new_tags:
                    response_parts.append(f"Теги: {' '.join(new_tags)}")

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

            await update.message.reply_text(
                f"✏️ *Редактирование @{username}*\n\n"
                f"Текущее описание: _{contact.description or 'не указано'}_\n"
                f"Теги: {' '.join(contact.tags) if contact.tags else '—'}\n\n"
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
