"""
Callback query handlers for inline buttons.
"""
from datetime import date, datetime, timedelta
from uuid import UUID

import pytz
from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler
from html import escape as html_escape

from src.bot.input_text import get_input_text
from src.bot.handlers.analytics import refresh_owner_dashboard
from src.bot.handlers.contacts import save_contact_from_username, show_contacts_page_for_user
from src.bot.handlers.notes import build_notes_view, handle_notes_callback
from src.bot.handlers.payments import (
    handle_donation_callback,
    handle_voice_subscription_callback,
    send_donation_menu,
)
from src.bot.handlers.support import (
    handle_support_admin_callback,
    handle_support_feedback_callback,
    handle_support_start,
)
from src.bot.keyboards import (
    get_contact_edit_keyboard,
    get_main_reply_keyboard,
    get_contact_keyboard,
    get_delete_confirm_keyboard,
    get_optional_context_keyboard,
    get_reminder_type_keyboard,
    get_regular_interval_keyboard,
    get_onetime_date_keyboard,
    get_existing_contact_keyboard,
    get_skip_contact_note_keyboard,
)
from src.bot.messages import (
    format_contact_card,
    format_contact_note_prompt,
    format_contact_note_saved,
    format_contact_note_skipped,
    format_contact_saved,
    format_reminder_set,
    format_no_reminder_set,
    format_custom_interval_prompt,
    format_custom_date_prompt,
    format_edit_contact_menu,
    format_description_prompt,
    format_edit_description_prompt,
    format_edit_tags_prompt,
    format_optional_context_prompt,
    format_username_not_found,
)
from src.bot.parsers.frequency import calculate_next_reminder, format_frequency
from src.config import settings
from src.db.engine import get_supabase
from src.db.repositories.contacts import ContactRepository
from src.db.repositories.users import UserRepository
from src.services.analytics_service import record_button_click
from src.services.contact_enrichment import enrich_contact_data
from src.services.contact_notes_service import (
    add_contact_note,
    delete_contact_notes,
    get_latest_contact_note,
)
from src.services.telegram_username_service import (
    UsernameValidationUnavailable,
    validate_public_username,
)


# ============ MENU HANDLERS ============


def _clear_contact_note_state(context: ContextTypes.DEFAULT_TYPE, contact_id: str | None = None) -> None:
    """Clear pending post-contact note flow, optionally only for one contact."""
    pending = context.user_data.get("awaiting_contact_note")
    if not pending:
        return

    if contact_id is None or pending.get("contact_id") == contact_id:
        context.user_data.pop("awaiting_contact_note", None)


def _clear_contact_lookup_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear the temporary state used for selecting a contact from the digest."""
    context.user_data.pop("awaiting_contact_lookup", None)
    context.user_data.pop("contact_list_page", None)


def _clear_edit_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear the temporary state used for contact field editing."""
    context.user_data.pop("editing_contact", None)
    context.user_data.pop("editing_field", None)


def _format_edit_reminder_text(contact) -> str:
    """Build a compact reminder summary for the edit menu."""
    if contact.status == "paused":
        return "На паузе"

    if contact.status == "one_time":
        reminder_date = contact.one_time_date or contact.next_reminder_date
        if reminder_date:
            return f"Однократно: {reminder_date.strftime('%d.%m.%Y')}"
        return "Однократное напоминание"

    freq_text = format_frequency(contact.reminder_frequency, contact.custom_interval_days)
    if contact.next_reminder_date:
        return f"{freq_text}, следующее {contact.next_reminder_date.strftime('%d.%m.%Y')}"
    return freq_text


def _describe_callback_button(data: str) -> tuple[str, str]:
    """Map callback payloads to stable analytics keys and readable labels."""
    if data.startswith("menu:add"):
        return "callback:menu:add", "Меню: Добавить контакт"
    if data.startswith("menu:list"):
        return "callback:menu:list", "Меню: Контакты"
    if data.startswith("menu:search"):
        return "callback:menu:search", "Меню: Поиск"
    if data.startswith("menu:notes"):
        return "callback:menu:notes", "Меню: Заметки"
    if data.startswith("menu:donate"):
        return "callback:menu:donate", "Меню: Поддержать"
    if data == "support:start":
        return "callback:support:start", "Поддержка: Открыть"
    if data.startswith("support_admin:reply:"):
        return "callback:support_admin_reply", "Поддержка: Админ ответить"
    if data.startswith("support_admin:skip:"):
        return "callback:support_admin_skip", "Поддержка: Админ пропустить"
    if data.startswith("support_feedback:helped:"):
        return "callback:support_feedback_helped", "Поддержка: Помогло"
    if data.startswith("support_feedback:followup:"):
        return "callback:support_feedback_followup", "Поддержка: Еще вопрос"
    if data.startswith("contacts_page:"):
        return "callback:contacts_page", "Контакты: пагинация"
    if data.startswith("contact_open:"):
        return "callback:contact_open", "Контакты: открыть карточку"
    if data == "pending_context:add":
        return "callback:pending_context_add", "Контакт: добавить контекст"
    if data == "pending_context:skip":
        return "callback:pending_context_skip", "Контакт: сохранить без контекста"
    if data == "confirm_contact":
        return "callback:confirm_contact", "Сохранить контакт"
    if data == "edit_draft":
        return "callback:edit_draft", "Исправить карточку"
    if data.startswith("reminder_type:regular"):
        return "callback:reminder_regular", "Напоминание: Регулярно"
    if data.startswith("reminder_type:onetime"):
        return "callback:reminder_onetime", "Напоминание: На дату"
    if data.startswith("reminder_type:none"):
        return "callback:reminder_none", "Напоминание: Без напоминаний"
    if data.startswith("reminder_type:back"):
        return "callback:reminder_back", "Напоминание: Назад"
    if data.startswith("interval:monthly"):
        return "callback:interval_monthly", "Интервал: Каждый месяц"
    if data.startswith("interval:bimonthly"):
        return "callback:interval_bimonthly", "Интервал: Раз в 2 месяца"
    if data.startswith("interval:quarterly"):
        return "callback:interval_quarterly", "Интервал: Раз в квартал"
    if data.startswith("interval:custom"):
        return "callback:interval_custom", "Интервал: Своя частота"
    if data.startswith("onetime:tomorrow"):
        return "callback:onetime_tomorrow", "Дата: Завтра"
    if data.startswith("onetime:week"):
        return "callback:onetime_week", "Дата: Через неделю"
    if data.startswith("onetime:month"):
        return "callback:onetime_month", "Дата: Через месяц"
    if data.startswith("onetime:custom"):
        return "callback:onetime_custom", "Дата: Указать вручную"
    if data.startswith("add_username_yes:"):
        return "callback:add_username_yes", "Добавить контакт из @username"
    if data == "add_username_no" or data.startswith("add_username_no:"):
        return "callback:add_username_no", "Не добавлять контакт из @username"
    if data.startswith("update_desc:"):
        return "callback:update_desc", "Контакт: Обновить описание"
    if data.startswith("update_reminder:"):
        return "callback:update_reminder", "Контакт: Настроить напоминание"
    if data.startswith("contacted:"):
        return "callback:contacted", "Контакт: Добавить заметку"
    if data.startswith("skip_note:"):
        return "callback:skip_note", "Заметка: Пропустить"
    if data.startswith("pause:"):
        return "callback:pause", "Контакт: Пауза"
    if data.startswith("resume:"):
        return "callback:resume", "Контакт: Возобновить"
    if data.startswith("edit:"):
        return "callback:edit", "Контакт: Изменить"
    if data.startswith("delete_yes:"):
        return "callback:delete_yes", "Контакт: Подтвердить удаление"
    if data.startswith("delete_no:"):
        return "callback:delete_no", "Контакт: Отменить удаление"
    if data.startswith("delete:"):
        return "callback:delete", "Контакт: Удалить"
    if data.startswith("notes:"):
        return "callback:notes_controls", "Заметки: Фильтры и страницы"
    if data.startswith("donate:"):
        if data in {"donate:custom", "donate:stars:custom"}:
            return "callback:donate:custom", "Поддержать: своя сумма"
        if data == "donate:sbp":
            return "callback:donate:sbp", "Поддержать: СБП"
        try:
            amount = int(data.split(":")[-1])
        except (IndexError, ValueError):
            amount = 0
        return f"callback:donate:{amount}", f"Поддержать: {amount} ⭐"
    if data.startswith("owner_dashboard:refresh"):
        return "callback:owner_dashboard_refresh", "Дашборд: Обновить"
    if data.startswith("owner_dashboard:"):
        parts = data.split(":")
        section = parts[1] if len(parts) > 1 else "overview"
        section_labels = {
            "overview": "Сводка",
            "users": "Пользователи",
            "contacts": "Контакты",
            "buttons": "Кнопки",
            "notes": "Заметки",
            "support": "Поддержка",
            "donations": "Донаты",
        }
        return f"callback:owner_dashboard:{section}", f"Дашборд: {section_labels.get(section, section)}"
    return "callback:other", f"Другая inline-кнопка: {data.split(':', 1)[0]}"

async def handle_menu_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Add contact' button."""
    query = update.callback_query
    await query.answer()

    _clear_contact_lookup_state(context)
    context.user_data.pop("editing_contact", None)
    context.user_data.pop("awaiting_search", None)
    context.user_data["awaiting_add"] = True

    await query.message.reply_text(
        "✨ <b>Новый контакт</b>\n\n"
        "Отправь одним сообщением:\n"
        "<code>@username</code> или <code>@username короткий контекст</code>\n\n"
        "Или просто перешли сообщение человека, и я помогу собрать карточку.",
        parse_mode="HTML",
    )


async def handle_menu_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'My contacts' button."""
    query = update.callback_query
    await query.answer()

    _clear_contact_lookup_state(context)
    user_id = update.effective_user.id
    await show_contacts_page_for_user(query.message, user_id, page=0)


async def handle_menu_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Search' button."""
    query = update.callback_query
    await query.answer()

    _clear_contact_lookup_state(context)
    context.user_data["awaiting_search"] = True

    await query.message.reply_text(
        "🔎 <b>Поиск по контактам</b>\n\n"
        "Напиши, кого или по какому контексту ищешь.\n\n"
        "Примеры:\n"
        "• <code>кто работает в IT?</code>\n"
        "• <code>контакты из Москвы</code>\n"
        "• <code>друзья</code>",
        parse_mode="HTML",
    )


async def handle_menu_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Notes' button in the inline menu."""
    query = update.callback_query
    await query.answer()

    text, keyboard = await build_notes_view(update.effective_user.id)
    await query.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard or get_main_reply_keyboard(update.effective_user.id),
    )


async def handle_menu_donate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Donate' button in the inline menu."""
    query = update.callback_query
    await query.answer()

    if update.effective_chat and update.effective_chat.type != "private":
        return

    if query.message:
        await send_donation_menu(query.message)


async def handle_contacts_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Move through paginated contacts list pages."""
    query = update.callback_query
    await query.answer()

    try:
        page = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        page = 0

    user_id = update.effective_user.id
    await show_contacts_page_for_user(
        query.message,
        user_id,
        page=page,
        edit=True,
    )


async def handle_contact_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open a contact card from the paginated contacts browser."""
    query = update.callback_query

    contact_id = query.data.split(":", 1)[1]
    user_id = update.effective_user.id

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if not contact or contact.user_id != user_id:
        await query.answer("Контакт не найден.", show_alert=True)
        return

    _clear_contact_lookup_state(context)
    context.user_data.pop("awaiting_add", None)
    context.user_data.pop("awaiting_search", None)

    await query.answer()
    await send_contact_card(query.message, contact)


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
    username = draft["username"].lower()
    display_name = draft.get("display_name")
    description = draft["description"]
    tags = draft["tags"]
    birthday_day = draft.get("birthday_day")
    birthday_month = draft.get("birthday_month")
    birthday_year = draft.get("birthday_year")
    source = draft.get("source", "manual_username")

    client = await get_supabase()
    # Ensure user exists
    user_repo = UserRepository(client)
    await user_repo.get_or_create(
        user_id=user_id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name,
    )

    contact_repo = ContactRepository(client)

    # Check if contact already exists
    existing = await contact_repo.get_by_username(user_id, username)
    if existing:
        await query.message.edit_text(
            f"Контакт @{username} уже существует.",
            parse_mode="HTML",
        )
        del context.user_data["draft_contact"]
        return

    if source != "forwarded":
        validation_available = True
        try:
            validation = await validate_public_username(username)
        except UsernameValidationUnavailable:
            validation_available = False
            validation = None

        if validation_available and validation and not validation.exists:
            del context.user_data["draft_contact"]
            await query.message.edit_text(
                format_username_not_found(username),
                parse_mode="HTML",
            )
            return

    # Create contact without reminder (will be set later)
    contact = await contact_repo.create(
        user_id=user_id,
        username=username,
        display_name=display_name,
        description=description,
        tags=tags,
        birthday_day=birthday_day,
        birthday_month=birthday_month,
        birthday_year=birthday_year,
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
        parse_mode="HTML",
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
        "source": draft.get("source", "manual_username"),
    }
    del context.user_data["draft_contact"]

    await query.message.edit_text(
        format_edit_description_prompt(draft["username"]),
        parse_mode="HTML",
    )


async def handle_pending_context_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the choice to add context now or continue without it."""
    query = update.callback_query
    await query.answer()

    pending = context.user_data.get("pending_contact")
    if not pending:
        await query.message.edit_text("Не нашёл черновик контакта. Пришли @username ещё раз.")
        return

    action = (query.data or "").split(":", 1)[1]
    pending["awaiting_context_choice"] = False

    if action == "add":
        await query.message.edit_text(
            format_description_prompt(
                pending["username"],
                pending.get("display_name"),
            ),
            parse_mode="HTML",
        )
        return

    if action == "skip":
        saved = await save_contact_from_username(
            query.message,
            update.effective_user,
            pending["username"],
            pending.get("raw_description", ""),
            edit=True,
        )
        if saved:
            context.user_data.pop("pending_contact", None)
        return

    await query.message.edit_text("Не понял выбор. Попробуй добавить контакт ещё раз.")


# ============ REMINDER TYPE HANDLERS ============

async def handle_reminder_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle reminder type selection."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    reminder_type = parts[1]
    contact_id = parts[2]

    if reminder_type == "back":
        await query.message.edit_text(
            "Какой формат напоминания выбрать?",
            reply_markup=get_reminder_type_keyboard(contact_id),
        )
        return

    if reminder_type == "regular":
        await query.message.edit_text(
            "Выбери удобную регулярную частоту напоминаний:",
            reply_markup=get_regular_interval_keyboard(contact_id),
        )

    elif reminder_type == "onetime":
        await query.message.edit_text(
            "Когда напомнить один раз?",
            reply_markup=get_onetime_date_keyboard(contact_id),
        )

    elif reminder_type == "none":
        # No reminder - pause the contact
        client = await get_supabase()
        repo = ContactRepository(client)
        contact = await repo.get_by_id(UUID(contact_id))

        if contact:
            await repo.update(contact.id, status="paused", next_reminder_date=None)
            _clear_edit_state(context)

            await query.message.edit_text(
                format_no_reminder_set(contact.username),
                parse_mode="HTML",
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
            parse_mode="HTML",
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

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if contact:
        await repo.update(
            contact.id,
            reminder_frequency=frequency,
            custom_interval_days=custom_days,
            next_reminder_date=next_date,
            status="active",
        )
        _clear_edit_state(context)

        freq_text = format_frequency(frequency, custom_days)
        await query.message.edit_text(
            format_reminder_set(contact.username, freq_text, next_date.strftime("%d.%m.%Y")),
            parse_mode="HTML",
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
            parse_mode="HTML",
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
        _clear_edit_state(context)

        await query.message.edit_text(
            format_reminder_set(contact.username, "однократно", reminder_date.strftime("%d.%m.%Y")),
            parse_mode="HTML",
        )
        await send_contact_card(query.message, await repo.get_by_id(UUID(contact_id)))


# ============ ADD USERNAME FROM MESSAGE HANDLERS ============

async def handle_add_username_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Yes' button when user confirms adding @username as contact."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":", 2)
    offer_id = None
    if len(parts) > 2:
        offer_id = parts[1]
        username = parts[2].lower()
    else:
        username = parts[1].lower() if len(parts) > 1 else ""
    offers = context.user_data.get("offered_contacts") or {}
    offered_contact = offers.pop(offer_id, None) if offer_id else None
    if offers:
        context.user_data["offered_contacts"] = offers
    else:
        context.user_data.pop("offered_contacts", None)
    raw_description = ""
    if offered_contact and offered_contact.get("username") == username:
        raw_description = (offered_contact.get("raw_description") or "").strip()

    user_id = update.effective_user.id

    client = await get_supabase()
    user_repo = UserRepository(client)
    await user_repo.get_or_create(
        user_id=user_id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name,
    )
    # Check if contact already exists (race condition protection)
    repo = ContactRepository(client)
    existing = await repo.get_by_username(user_id, username)
    validation_available = True
    try:
        validation = await validate_public_username(username)
    except UsernameValidationUnavailable:
        validation_available = False
        validation = None

    if validation_available and validation and not validation.exists and not existing:
        await query.message.edit_text(
            format_username_not_found(username),
            parse_mode="HTML",
        )
        return

    if existing:
        await query.message.edit_text(
            f"Контакт <b>@{username}</b> уже есть в списке.\n"
            "Открой «👥 Контакты», если хочешь обновить карточку.",
            parse_mode="HTML",
        )
        return

    if not raw_description:
        context.user_data["pending_contact"] = {
            "username": username,
            "display_name": getattr(validation, "display_name", None) if validation else None,
            "source": "manual_username",
            "awaiting_context_choice": True,
        }
        await query.message.edit_text(
            format_optional_context_prompt(
                username,
                getattr(validation, "display_name", None) if validation else None,
            ),
            parse_mode="HTML",
            reply_markup=get_optional_context_keyboard(),
        )
        return

    enriched = await enrich_contact_data(
        username=username,
        raw_description=raw_description,
        profile=validation,
        fetch_profile_if_missing=validation_available,
    )
    contact = await repo.create(
        user_id=user_id,
        username=username,
        display_name=enriched.display_name,
        description=enriched.description or None,
        tags=enriched.tags,
        birthday_day=enriched.birthday_day,
        birthday_month=enriched.birthday_month,
        birthday_year=enriched.birthday_year,
        reminder_frequency="monthly",
        next_reminder_date=date.today() + timedelta(days=30),
        status="active",
    )
    context.user_data["setting_reminder_for"] = str(contact.id)

    await query.message.edit_text(
        format_contact_saved(username),
        parse_mode="HTML",
        reply_markup=get_reminder_type_keyboard(str(contact.id)),
    )


async def handle_add_username_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'No' button when user declines adding @username as contact."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 1)
    offer_id = parts[1] if len(parts) > 1 else None
    offers = context.user_data.get("offered_contacts") or {}
    if offer_id:
        offers.pop(offer_id, None)
    if offers:
        context.user_data["offered_contacts"] = offers
    else:
        context.user_data.pop("offered_contacts", None)

    await query.message.delete()


# ============ EXISTING CONTACT HANDLERS ============

async def handle_update_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Update description' for existing contact."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if contact:
        _clear_contact_lookup_state(context)
        context.user_data.pop("awaiting_add", None)
        context.user_data.pop("awaiting_search", None)
        context.user_data["editing_contact"] = contact_id
        context.user_data["editing_field"] = "description"

        await query.message.edit_text(
            format_edit_description_prompt(contact.username),
            parse_mode="HTML",
        )


async def handle_update_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Change reminder' for existing contact."""
    query = update.callback_query
    await query.answer()

    _clear_contact_lookup_state(context)
    contact_id = query.data.split(":")[1]
    context.user_data["editing_contact"] = contact_id
    context.user_data["editing_field"] = "reminder"

    await query.message.edit_text(
        "Какой формат напоминания выбрать?",
        reply_markup=get_reminder_type_keyboard(contact_id),
    )


async def handle_edit_field_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the inline choice of what exactly to edit."""
    query = update.callback_query
    await query.answer()

    _, field, contact_id = (query.data or "").split(":", 2)
    user_id = update.effective_user.id

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if not contact or contact.user_id != user_id:
        await query.message.edit_text("Контакт не найден.")
        return

    _clear_contact_lookup_state(context)
    context.user_data.pop("awaiting_add", None)
    context.user_data.pop("awaiting_search", None)
    context.user_data["editing_contact"] = contact_id
    context.user_data["editing_field"] = field

    if field == "description":
        await query.message.edit_text(
            format_edit_description_prompt(contact.username),
            parse_mode="HTML",
        )
        return

    if field == "tags":
        await query.message.edit_text(
            format_edit_tags_prompt(contact.username),
            parse_mode="HTML",
        )
        return

    if field == "reminder":
        await query.message.edit_text(
            "Какой формат напоминания выбрать?",
            reply_markup=get_reminder_type_keyboard(contact_id),
        )
        return


# ============ CONTACT ACTION HANDLERS ============

async def handle_contacted_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Contacted' button."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]
    user_id = update.effective_user.id
    tz = pytz.timezone(settings.TIMEZONE)
    now = datetime.now(tz)

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if not contact or contact.user_id != user_id:
        await query.message.edit_text("Контакт не найден.")
        return

    _clear_contact_note_state(context)
    updates = {"last_contacted_at": now}

    if contact.status == "one_time":
        updates["status"] = "paused"
        await repo.update(contact.id, **updates)
        await query.message.edit_text(
            f"✅ Отлично, связь с <b>@{contact.username}</b> отмечена.\n"
            "Это было разовое напоминание, поэтому карточка автоматически ушла на паузу.",
            parse_mode="HTML",
        )
    else:
        next_date = calculate_next_reminder(
            contact.reminder_frequency, contact.custom_interval_days
        )
        updates["next_reminder_date"] = next_date

        await repo.update(contact.id, **updates)
        # Update the message with new date
        await send_contact_card(
            query.message,
            await repo.get_by_id(UUID(contact_id)),
            edit=True,
            prefix=f"✅ Связь отмечена. Следующее напоминание: {next_date.strftime('%d.%m.%Y')}"
        )

    context.user_data["awaiting_contact_note"] = {
        "contact_id": str(contact.id),
        "username": contact.username,
    }
    await query.message.reply_text(
        format_contact_note_prompt(contact.username),
        parse_mode="HTML",
        reply_markup=get_skip_contact_note_keyboard(str(contact.id)),
    )


async def handle_contact_note_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle the optional post-contact note input."""
    pending = context.user_data.get("awaiting_contact_note")
    if not pending:
        return False

    text = get_input_text(update, context, strip=True) or ""
    if not text:
        return True

    if len(text) > 500:
        await update.message.reply_text(
            "Сделай заметку чуть короче, до 500 символов.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    contact_id = pending["contact_id"]
    user_id = update.effective_user.id

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if not contact or contact.user_id != user_id:
        _clear_contact_note_state(context)
        await update.message.reply_text(
            "Не смог найти карточку для этой заметки. Попробуй открыть контакт заново.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    tz = pytz.timezone(settings.TIMEZONE)
    now = datetime.now(tz)
    await add_contact_note(str(contact.id), text, now)
    _clear_contact_note_state(context, str(contact.id))

    await update.message.reply_text(
        format_contact_note_saved(contact.username),
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard(update.effective_user.id),
    )
    await send_contact_card(update.message, contact)
    return True


async def handle_skip_contact_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Skip the optional post-contact note step."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]
    pending = context.user_data.get("awaiting_contact_note")
    username = pending.get("username") if pending and pending.get("contact_id") == contact_id else None
    _clear_contact_note_state(context, contact_id)

    text = format_contact_note_skipped(username) if username else "Ок, оставил без заметки."
    await query.message.edit_text(text, parse_mode="HTML")


async def handle_pause_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Pause' button."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]
    user_id = update.effective_user.id

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if not contact or contact.user_id != user_id:
        await query.message.edit_text("Контакт не найден.")
        return

    if contact.status == "paused":
        await query.answer("Контакт уже на паузе", show_alert=True)
        return

    await repo.update(contact.id, status="paused")

    # Update the card with new status
    await send_contact_card(
        query.message,
        await repo.get_by_id(UUID(contact_id)),
        edit=True,
        prefix="⏸️ Напоминания приостановлены"
    )


async def handle_resume_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Resume' button."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]
    user_id = update.effective_user.id

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if not contact or contact.user_id != user_id:
        await query.message.edit_text("Контакт не найден.")
        return

    next_date = calculate_next_reminder(
        contact.reminder_frequency, contact.custom_interval_days
    )

    await repo.update(contact.id, status="active", next_reminder_date=next_date)

    await send_contact_card(
        query.message,
        await repo.get_by_id(UUID(contact_id)),
        edit=True,
        prefix=f"▶️ Напоминания снова активны. Следующее: {next_date.strftime('%d.%m.%Y')}"
    )


async def handle_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Edit' button."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]
    user_id = update.effective_user.id

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if not contact or contact.user_id != user_id:
        await query.message.edit_text("Контакт не найден.")
        return

    _clear_contact_lookup_state(context)
    context.user_data.pop("awaiting_add", None)
    context.user_data.pop("awaiting_search", None)
    _clear_edit_state(context)

    await query.message.reply_text(
        format_edit_contact_menu(
            contact.username,
            contact.description,
            contact.tags,
            _format_edit_reminder_text(contact),
        ),
        parse_mode="HTML",
        reply_markup=get_contact_edit_keyboard(contact_id),
    )


async def handle_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Delete' button - show confirmation."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]
    user_id = update.effective_user.id

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if not contact or contact.user_id != user_id:
        await query.message.edit_text("Контакт не найден.")
        return

    await query.message.edit_text(
        f"❌ Удалить карточку <b>@{contact.username}</b>?\n"
        "Все заметки по этому контакту тоже будут удалены.",
        parse_mode="HTML",
        reply_markup=get_delete_confirm_keyboard(contact_id),
    )


async def handle_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle delete confirmation."""
    query = update.callback_query
    await query.answer()

    contact_id = query.data.split(":")[1]
    user_id = update.effective_user.id

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if not contact or contact.user_id != user_id:
        await query.message.edit_text("Контакт не найден.")
        return

    username = contact.username
    await repo.delete(contact.id)
    await delete_contact_notes(str(contact.id))
    _clear_contact_note_state(context, str(contact.id))

    await query.message.edit_text(
        f"✅ Карточка <b>@{username}</b> удалена.",
        parse_mode="HTML",
    )


async def handle_delete_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle delete cancellation."""
    query = update.callback_query
    await query.answer("Отменено")

    contact_id = query.data.split(":")[1]
    user_id = update.effective_user.id

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if contact and contact.user_id == user_id:
        await send_contact_card(query.message, contact, edit=True)
    else:
        await query.message.edit_text("Операция отменена. Карточка осталась без изменений.")


# ============ HELPER FUNCTIONS ============

async def send_contact_card(message, contact, edit: bool = False, prefix: str = "") -> None:
    """Send or edit a contact card with inline buttons."""
    latest_note = await get_latest_contact_note(str(contact.id))
    text = format_contact_card(
        username=contact.username,
        description=contact.description,
        tags=contact.tags,
        status=contact.status,
        next_reminder_date=contact.next_reminder_date,
        one_time_date=contact.one_time_date,
        prefix=prefix,
        display_name=contact.display_name,
        last_note=latest_note.text if latest_note else None,
        birthday_day=getattr(contact, "birthday_day", None),
        birthday_month=getattr(contact, "birthday_month", None),
        birthday_year=getattr(contact, "birthday_year", None),
    )
    keyboard = get_contact_keyboard(str(contact.id), contact.status)

    if edit:
        await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def send_contact_card_to_chat(bot, chat_id: int, contact, prefix: str = "") -> None:
    """Send contact card to a specific chat (for scheduler jobs)."""
    latest_note = await get_latest_contact_note(str(contact.id))
    text = format_contact_card(
        username=contact.username,
        description=contact.description,
        tags=contact.tags,
        status=contact.status,
        next_reminder_date=contact.next_reminder_date,
        one_time_date=contact.one_time_date,
        prefix=prefix,
        display_name=contact.display_name,
        last_note=latest_note.text if latest_note else None,
        birthday_day=getattr(contact, "birthday_day", None),
        birthday_month=getattr(contact, "birthday_month", None),
        birthday_year=getattr(contact, "birthday_year", None),
    )
    keyboard = get_contact_keyboard(str(contact.id), contact.status)
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="HTML")


# ============ CALLBACK ROUTER ============

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route callback queries to appropriate handlers."""
    query = update.callback_query
    data = query.data
    key, label = _describe_callback_button(data)
    if not key.startswith("callback:owner_dashboard"):
        await record_button_click(update.effective_user.id, key, label)

    # Menu actions
    if data.startswith("menu:"):
        action = data.split(":")[1]
        if action == "add":
            await handle_menu_add(update, context)
        elif action == "list":
            await handle_menu_list(update, context)
        elif action == "search":
            await handle_menu_search(update, context)
        elif action == "notes":
            await handle_menu_notes(update, context)
        elif action == "donate":
            await handle_menu_donate(update, context)
    elif data.startswith("contacts_page:"):
        await handle_contacts_page(update, context)
    elif data.startswith("contact_open:"):
        await handle_contact_open(update, context)
    elif data.startswith("pending_context:"):
        await handle_pending_context_choice(update, context)
    elif data.startswith("notes:"):
        await handle_notes_callback(update, context)
    elif data.startswith("donate:"):
        await handle_donation_callback(update, context)
    elif data.startswith("voice_sub:"):
        await handle_voice_subscription_callback(update, context)
    elif data.startswith("owner_dashboard:"):
        await refresh_owner_dashboard(update, context)
    elif data == "support:start":
        await handle_support_start(update, context)
    elif data.startswith("support_admin:"):
        await handle_support_admin_callback(update, context)
    elif data.startswith("support_feedback:"):
        await handle_support_feedback_callback(update, context)

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
    elif data == "add_username_no" or data.startswith("add_username_no:"):
        await handle_add_username_no(update, context)

    # Existing contact options
    elif data.startswith("update_desc:"):
        await handle_update_description(update, context)
    elif data.startswith("update_reminder:"):
        await handle_update_reminder(update, context)
    elif data.startswith("edit_field:"):
        await handle_edit_field_selection(update, context)

    # Contact actions
    elif data.startswith("contacted:"):
        await handle_contacted_callback(update, context)
    elif data.startswith("skip_note:"):
        await handle_skip_contact_note(update, context)
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
