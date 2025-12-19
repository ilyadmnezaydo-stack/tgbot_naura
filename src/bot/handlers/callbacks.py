"""
Callback query handlers for inline buttons.
"""
from datetime import datetime
from uuid import UUID

import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from src.bot.parsers.frequency import calculate_next_reminder, format_frequency
from src.config import settings
from src.db.engine import get_session
from src.db.repositories.contacts import ContactRepository
from src.db.repositories.users import UserRepository
from src.services.ai_service import AIService


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Create main menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("➕ Добавить контакт", callback_data="menu:add")],
        [InlineKeyboardButton("📋 Мои контакты", callback_data="menu:list")],
        [InlineKeyboardButton("🔍 Найти контакт", callback_data="menu:search")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_contact_keyboard(contact_id: str, status: str) -> InlineKeyboardMarkup:
    """Create keyboard for a contact based on its status."""
    if status == "paused":
        keyboard = [
            [
                InlineKeyboardButton("▶️ Продолжить", callback_data=f"resume:{contact_id}"),
                InlineKeyboardButton("✏️ Изменить", callback_data=f"edit:{contact_id}"),
            ],
            [
                InlineKeyboardButton("❌ Удалить", callback_data=f"delete:{contact_id}"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("✅ Написал", callback_data=f"contacted:{contact_id}"),
                InlineKeyboardButton("✏️ Изменить", callback_data=f"edit:{contact_id}"),
            ],
            [
                InlineKeyboardButton("⏸️ Пауза", callback_data=f"pause:{contact_id}"),
                InlineKeyboardButton("❌ Удалить", callback_data=f"delete:{contact_id}"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_delete_confirm_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    """Create confirmation keyboard for delete action."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"delete_yes:{contact_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"delete_no:{contact_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============ MENU HANDLERS ============

async def handle_menu_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Add contact' button."""
    query = update.callback_query
    await query.answer()

    context.user_data["awaiting_add"] = True

    await query.message.reply_text(
        "Отправь контакт в формате:\n\n"
        "`@username описание контакта. частота`\n\n"
        "Примеры:\n"
        "• `@ivan коллега из маркетинга. раз в неделю`\n"
        "• `@anna друг детства. раз в месяц`\n"
        "• `@peter партнер по бизнесу`",
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

        await query.message.reply_text(
            f"Редактирование @{contact.username}\n\n"
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
    # Format contact info
    if contact.status == "paused":
        status_text = "⏸️ на паузе"
    elif contact.status == "one_time":
        date_str = (
            contact.one_time_date.strftime("%d.%m")
            if contact.one_time_date
            else contact.next_reminder_date.strftime("%d.%m") if contact.next_reminder_date else "?"
        )
        status_text = f"📅 {date_str}"
    else:
        next_date = contact.next_reminder_date.strftime("%d.%m") if contact.next_reminder_date else "?"
        status_text = f"след. {next_date}"

    tags_text = " ".join(contact.tags) if contact.tags else ""
    desc_text = contact.description or ""

    text = f"{prefix}*@{contact.username}* ({status_text})\n"
    if desc_text:
        text += f"{desc_text}\n"
    if tags_text:
        text += f"{tags_text}"

    keyboard = get_contact_keyboard(str(contact.id), contact.status)

    if edit:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


# ============ CALLBACK ROUTER ============

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route callback queries to appropriate handlers."""
    query = update.callback_query
    data = query.data

    if data.startswith("menu:"):
        action = data.split(":")[1]
        if action == "add":
            await handle_menu_add(update, context)
        elif action == "list":
            await handle_menu_list(update, context)
        elif action == "search":
            await handle_menu_search(update, context)

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
