"""
Callback query handlers for inline buttons.
"""
from datetime import date, datetime, timedelta
from uuid import UUID

import pytz
from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.helpers import escape_markdown

from src.bot.keyboards import (
    get_main_menu_keyboard,
    get_contact_keyboard,
    get_delete_confirm_keyboard,
    get_reminder_type_keyboard,
    get_regular_interval_keyboard,
    get_onetime_date_keyboard,
    get_existing_contact_keyboard,
)
from src.bot.messages import (
    format_contact_card,
    format_contact_saved,
    format_reminder_set,
    format_no_reminder_set,
    format_custom_interval_prompt,
    format_custom_date_prompt,
    format_edit_description_prompt,
)
from src.bot.parsers.frequency import calculate_next_reminder, format_frequency
from src.config import settings
from src.db.engine import get_session
from src.db.repositories.contacts import ContactRepository
from src.db.repositories.users import UserRepository


# ============ MENU HANDLERS ============

async def handle_menu_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Add contact' button."""
    query = update.callback_query
    await query.answer()

    context.user_data["awaiting_add"] = True

    await query.message.reply_text(
        "Отправь контакт в формате:\n\n"
        "`@username описание контакта`\n\n"
        "Или перешли сообщение от нужного человека.",
        parse_mode="Markdown",
    )


async def handle_menu_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'My contacts' button."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    async with get_session() as session:
        contact_repo = ContactRepository(session)
        contacts = await contact_repo.get_all_for_user(user_id)

        if not contacts:
            await query.message.reply_text(
                "У тебя пока нет контактов.\n"
                "Нажми *➕ Добавить контакт* чтобы добавить первый.",
                parse_mode="Markdown",
                reply_markup=get_main_menu_keyboard(),
            )
            return

        await query.message.reply_text(f"📋 *Твои контакты ({len(contacts)}):*", parse_mode="Markdown")

        for contact in contacts:
            await send_contact_card(query.message, contact)


async def handle_menu_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Search' button."""
    query = update.callback_query
    await query.answer()

    context.user_data["awaiting_search"] = True

    await query.message.reply_text(
        "Введи поисковый запрос.\n\n"
        "Примеры:\n"
        "• `кто работает в IT?`\n"
        "• `контакты из Москвы`\n"
        "• `друзья`",
        parse_mode="Markdown",
    )


# ============ CONTACT CONFIRMATION HANDLERS ============

async def handle_confirm_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'All correct' button - save contact and show reminder options."""
    query = update.callback_query
    await query.answer()

    draft = context.user_data.get("draft_contact")
    if not draft:
        await query.message.edit_text("Ошибка: данные контакта не найдены.")
        return

    user_id = update.effective_user.id
    username = draft["username"]
    display_name = draft.get("display_name")
    description = draft["description"]
    tags = draft["tags"]

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
            safe_username = escape_markdown(username, version=1) if username else "контакт"
            await query.message.edit_text(
                f"Контакт @{safe_username} уже существует.",
                parse_mode="Markdown",
            )
            del context.user_data["draft_contact"]
            return

        # Create contact without reminder (will be set later)
        contact = await contact_repo.create(
            user_id=user_id,
            username=username,
            display_name=display_name,
            description=description,
            tags=tags,
            reminder_frequency="monthly",  # Default, will be updated
            next_reminder_date=date.today() + timedelta(days=30),
            status="active",
        )

        # Store contact_id for reminder selection
        context.user_data["setting_reminder_for"] = str(contact.id)

    # Clear draft
    del context.user_data["draft_contact"]

    # Show reminder type selection
    await query.message.edit_text(
        format_contact_saved(username),
        parse_mode="Markdown",
        reply_markup=get_reminder_type_keyboard(str(contact.id)),
    )


async def handle_edit_draft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Edit' button on draft - ask for new description."""
    query = update.callback_query
    await query.answer()

    draft = context.user_data.get("draft_contact")
    if not draft:
        await query.message.edit_text("Ошибка: данные контакта не найдены.")
        return

    # Move draft back to pending for re-entry
    context.user_data["pending_contact"] = {
        "username": draft["username"],
        "display_name": draft.get("display_name") or draft["username"],
    }
    del context.user_data["draft_contact"]

    await query.message.edit_text(
        format_edit_description_prompt(draft["username"]),
        parse_mode="Markdown",
    )


# ============ REMINDER TYPE HANDLERS ============

async def handle_reminder_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle reminder type selection."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    reminder_type = parts[1]
    contact_id = parts[2]

    if reminder_type == "back":
        # Go back to reminder type selection
        await query.message.edit_reply_markup(
            reply_markup=get_reminder_type_keyboard(contact_id)
        )
        return

    if reminder_type == "regular":
        # Show interval options
        await query.message.edit_text(
            "Выбери интервал напоминания:",
            reply_markup=get_regular_interval_keyboard(contact_id),
        )

    elif reminder_type == "onetime":
        # Show date options
        await query.message.edit_text(
            "Когда напомнить?",
            reply_markup=get_onetime_date_keyboard(contact_id),
        )

    elif reminder_type == "none":
        # No reminder - pause the contact
        async with get_session() as session:
            repo = ContactRepository(session)
            contact = await repo.get_by_id(UUID(contact_id))

            if contact:
                await repo.update(contact, status="paused", next_reminder_date=None)

                await query.message.edit_text(
                    format_no_reminder_set(contact.username),
                    parse_mode="Markdown",
                )
                await send_contact_card(query.message, await repo.get_by_id(UUID(contact_id)))


# ============ REGULAR INTERVAL HANDLERS ============

async def handle_interval_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle regular interval selection."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    interval = parts[1]
    contact_id = parts[2]

    if interval == "custom":
        # Ask for custom interval
        context.user_data["awaiting_custom_interval"] = contact_id
        await query.message.edit_text(
            format_custom_interval_prompt(),
            parse_mode="Markdown",
        )
        return

    # Map interval to frequency
    interval_map = {
        "monthly": ("monthly", None, 30),
        "bimonthly": ("custom", 60, 60),
        "quarterly": ("custom", 90, 90),
    }

    frequency, custom_days, days = interval_map.get(interval, ("monthly", None, 30))
    next_date = date.today() + timedelta(days=days)

    async with get_session() as session:
        repo = ContactRepository(session)
        contact = await repo.get_by_id(UUID(contact_id))

        if contact:
            await repo.update(
                contact,
                reminder_frequency=frequency,
                custom_interval_days=custom_days,
                next_reminder_date=next_date,
                status="active",
            )

            freq_text = format_frequency(frequency, custom_days)
            await query.message.edit_text(
                format_reminder_set(contact.username, freq_text, next_date.strftime("%d.%m.%Y")),
                parse_mode="Markdown",
            )
            await send_contact_card(query.message, await repo.get_by_id(UUID(contact_id)))


# ============ ONE-TIME DATE HANDLERS ============

async def handle_onetime_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle one-time reminder date selection."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    date_option = parts[1]
    contact_id = parts[2]

    if date_option == "custom":
        # Ask for custom date
        context.user_data["awaiting_custom_date"] = contact_id
        await query.message.edit_text(
            format_custom_date_prompt(),
            parse_mode="Markdown",
        )
        return

    # Calculate date
    today = date.today()
    date_map = {
        "tomorrow": today + timedelta(days=1),
        "week": today + timedelta(days=7),
        "month": today + timedelta(days=30),
    }

    reminder_date = date_map.get(date_option, today + timedelta(days=1))

    async with get_session() as session:
        repo = ContactRepository(session)
        contact = await repo.get_by_id(UUID(contact_id))

        if contact:
            await repo.update(
                contact,
                reminder_frequency="one_time",
                next_reminder_date=reminder_date,
                one_time_date=reminder_date,
                status="one_time",
            )

            await query.message.edit_text(
                format_reminder_set(contact.username, "однократно", reminder_date.strftime("%d.%m.%Y")),
                parse_mode="Markdown",
            )
            await send_contact_card(query.message, await repo.get_by_id(UUID(contact_id)))


# ============ ADD USERNAME FROM MESSAGE HANDLERS ============

async def handle_add_username_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Yes' button when user confirms adding @username as contact."""
    query = update.callback_query
    await query.answer()

    # Extract username from callback data
    username = query.data.split(":")[1]

    user_id = update.effective_user.id

    async with get_session() as session:
        # Check if contact already exists (race condition protection)
        repo = ContactRepository(session)
        existing = await repo.get_by_username(user_id, username)

        if existing:
            await query.message.edit_text(
                f"Контакт @{username} уже существует в твоём списке."
            )
            return

    # Store username in pending_contact and ask for description
    context.user_data["pending_contact"] = {
        "username": username,
        "display_name": username,  # No display_name available from @mention
    }

    safe_username = escape_markdown(username, version=1) if username else "контакт"
    await query.message.edit_text(
        f"Введи описание для @{safe_username}:",
        parse_mode="Markdown",
    )


async def handle_add_username_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'No' button when user declines adding @username as contact."""
    query = update.callback_query
    await query.answer()

    await query.message.delete()


# ============ EXISTING CONTACT HANDLERS ============

async def handle_update_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Update description' for existing contact."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]

    async with get_session() as session:
        repo = ContactRepository(session)
        contact = await repo.get_by_id(UUID(contact_id))

        if contact:
            context.user_data["editing_contact"] = contact_id
            context.user_data["editing_field"] = "description"

            await query.message.edit_text(
                format_edit_description_prompt(contact.username),
                parse_mode="Markdown",
            )


async def handle_update_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Change reminder' for existing contact."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]

    await query.message.edit_text(
        "Выбери тип напоминания:",
        reply_markup=get_reminder_type_keyboard(contact_id),
    )


# ============ CONTACT ACTION HANDLERS ============

async def handle_contacted_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Contacted' button."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]
    user_id = update.effective_user.id
    tz = pytz.timezone(settings.TIMEZONE)
    now = datetime.now(tz)

    async with get_session() as session:
        repo = ContactRepository(session)
        contact = await repo.get_by_id(UUID(contact_id))

        if not contact or contact.user_id != user_id:
            await query.message.edit_text("Контакт не найден.")
            return

        updates = {"last_contacted_at": now}

        if contact.status == "one_time":
            updates["status"] = "paused"
            await repo.update(contact, **updates)
            await repo.add_history(contact.id, "contacted", "One-time reminder completed")

            await query.message.edit_text(
                f"✅ Отлично! Отметил, что ты связался с @{contact.username}.\n"
                f"Это было одноразовое напоминание — контакт поставлен на паузу."
            )
        else:
            next_date = calculate_next_reminder(
                contact.reminder_frequency, contact.custom_interval_days
            )
            updates["next_reminder_date"] = next_date

            await repo.update(contact, **updates)
            await repo.add_history(contact.id, "contacted")

            # Update the message with new date
            await send_contact_card(
                query.message,
                await repo.get_by_id(UUID(contact_id)),
                edit=True,
                prefix=f"✅ Отметил! Следующее напоминание: {next_date.strftime('%d.%m.%Y')}\n\n"
            )


async def handle_pause_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Pause' button."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]
    user_id = update.effective_user.id

    async with get_session() as session:
        repo = ContactRepository(session)
        contact = await repo.get_by_id(UUID(contact_id))

        if not contact or contact.user_id != user_id:
            await query.message.edit_text("Контакт не найден.")
            return

        if contact.status == "paused":
            await query.answer("Контакт уже на паузе", show_alert=True)
            return

        await repo.update(contact, status="paused")
        await repo.add_history(contact.id, "paused")

        # Update the card with new status
        await send_contact_card(
            query.message,
            await repo.get_by_id(UUID(contact_id)),
            edit=True,
            prefix="⏸️ Напоминания приостановлены\n\n"
        )


async def handle_resume_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Resume' button."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]
    user_id = update.effective_user.id

    async with get_session() as session:
        repo = ContactRepository(session)
        contact = await repo.get_by_id(UUID(contact_id))

        if not contact or contact.user_id != user_id:
            await query.message.edit_text("Контакт не найден.")
            return

        next_date = calculate_next_reminder(
            contact.reminder_frequency, contact.custom_interval_days
        )

        await repo.update(contact, status="active", next_reminder_date=next_date)
        await repo.add_history(contact.id, "resumed")

        await send_contact_card(
            query.message,
            await repo.get_by_id(UUID(contact_id)),
            edit=True,
            prefix=f"▶️ Напоминания возобновлены! Следующее: {next_date.strftime('%d.%m.%Y')}\n\n"
        )


async def handle_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Edit' button."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]
    user_id = update.effective_user.id

    async with get_session() as session:
        repo = ContactRepository(session)
        contact = await repo.get_by_id(UUID(contact_id))

        if not contact or contact.user_id != user_id:
            await query.message.edit_text("Контакт не найден.")
            return

        context.user_data["editing_contact"] = contact_id

        # Escape markdown in user-provided text
        escaped_username = escape_markdown(contact.username, version=1) if contact.username else "контакт"
        safe_desc = escape_markdown(contact.description, version=1) if contact.description else "не указано"
        safe_tags = escape_markdown(" ".join(contact.tags), version=1) if contact.tags else "—"
        freq_text = format_frequency(contact.reminder_frequency, contact.custom_interval_days)

        await query.message.reply_text(
            f"✏️ *Редактирование @{escaped_username}*\n\n"
            f"📝 Описание: _{safe_desc}_\n"
            f"🏷 Теги: {safe_tags}\n"
            f"🔔 Напоминание: {freq_text}\n\n"
            f"Отправь новые данные:\n"
            f"• Новое описание\n"
            f"• Или новую частоту (раз в неделю, раз в месяц...)\n"
            f"• Или теги (#tag1 #tag2)\n\n"
            f"Отправь `/cancel` для отмены.",
            parse_mode="Markdown",
        )


async def handle_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Delete' button - show confirmation."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]
    user_id = update.effective_user.id

    async with get_session() as session:
        repo = ContactRepository(session)
        contact = await repo.get_by_id(UUID(contact_id))

        if not contact or contact.user_id != user_id:
            await query.message.edit_text("Контакт не найден.")
            return

        await query.message.edit_text(
            f"❌ Удалить контакт @{contact.username}?",
            reply_markup=get_delete_confirm_keyboard(contact_id),
        )


async def handle_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle delete confirmation."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]
    user_id = update.effective_user.id

    async with get_session() as session:
        repo = ContactRepository(session)
        contact = await repo.get_by_id(UUID(contact_id))

        if not contact or contact.user_id != user_id:
            await query.message.edit_text("Контакт не найден.")
            return

        username = contact.username
        await repo.delete(contact)

        await query.message.edit_text(f"✅ Контакт @{username} удалён.")


async def handle_delete_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle delete cancellation."""
    query = update.callback_query
    await query.answer("Отменено")

    contact_id = query.data.split(":")[1]
    user_id = update.effective_user.id

    async with get_session() as session:
        repo = ContactRepository(session)
        contact = await repo.get_by_id(UUID(contact_id))

        if contact and contact.user_id == user_id:
            await send_contact_card(query.message, contact, edit=True)
        else:
            await query.message.edit_text("Операция отменена.")


# ============ HELPER FUNCTIONS ============

async def send_contact_card(message, contact, edit: bool = False, prefix: str = "") -> None:
    """Send or edit a contact card with inline buttons."""
    text = format_contact_card(
        username=contact.username,
        description=contact.description,
        tags=contact.tags,
        status=contact.status,
        next_reminder_date=contact.next_reminder_date,
        one_time_date=contact.one_time_date,
        prefix=prefix,
        display_name=contact.display_name,
    )
    keyboard = get_contact_keyboard(str(contact.id), contact.status)

    if edit:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def send_contact_card_to_chat(bot, chat_id: int, contact) -> None:
    """Send contact card to a specific chat (for scheduler jobs)."""
    text = format_contact_card(
        username=contact.username,
        description=contact.description,
        tags=contact.tags,
        status=contact.status,
        next_reminder_date=contact.next_reminder_date,
        one_time_date=contact.one_time_date,
        display_name=contact.display_name,
    )
    keyboard = get_contact_keyboard(str(contact.id), contact.status)
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="Markdown")


# ============ CALLBACK ROUTER ============

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route callback queries to appropriate handlers."""
    query = update.callback_query
    data = query.data

    # Menu actions
    if data.startswith("menu:"):
        action = data.split(":")[1]
        if action == "add":
            await handle_menu_add(update, context)
        elif action == "list":
            await handle_menu_list(update, context)
        elif action == "search":
            await handle_menu_search(update, context)

    # Contact confirmation
    elif data == "confirm_contact":
        await handle_confirm_contact(update, context)
    elif data == "edit_draft":
        await handle_edit_draft(update, context)

    # Reminder type selection
    elif data.startswith("reminder_type:"):
        await handle_reminder_type(update, context)

    # Regular interval selection
    elif data.startswith("interval:"):
        await handle_interval_selection(update, context)

    # One-time date selection
    elif data.startswith("onetime:"):
        await handle_onetime_date(update, context)

    # Add username from message
    elif data.startswith("add_username_yes:"):
        await handle_add_username_yes(update, context)
    elif data == "add_username_no":
        await handle_add_username_no(update, context)

    # Existing contact options
    elif data.startswith("update_desc:"):
        await handle_update_description(update, context)
    elif data.startswith("update_reminder:"):
        await handle_update_reminder(update, context)

    # Contact actions
    elif data.startswith("contacted:"):
        await handle_contacted_callback(update, context)
    elif data.startswith("pause:"):
        await handle_pause_callback(update, context)
    elif data.startswith("resume:"):
        await handle_resume_callback(update, context)
    elif data.startswith("edit:"):
        await handle_edit_callback(update, context)
    elif data.startswith("delete:"):
        await handle_delete_callback(update, context)
    elif data.startswith("delete_yes:"):
        await handle_delete_confirm(update, context)
    elif data.startswith("delete_no:"):
        await handle_delete_cancel(update, context)


def get_callback_handler() -> CallbackQueryHandler:
    """Return callback query handler."""
    return CallbackQueryHandler(callback_router)
