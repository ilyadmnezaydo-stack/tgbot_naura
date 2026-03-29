"""
Contact management handlers: add, update, list, search.
"""
import re
from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from src.bot.input_text import get_input_text
from src.bot.keyboards import (
    get_contact_edit_keyboard,
    get_contacts_browser_keyboard,
    get_main_reply_keyboard,
    get_optional_context_keyboard,
    get_reminder_type_keyboard,
)
from src.bot.messages import (
    format_contact_lookup_ambiguous,
    format_contact_lookup_not_found,
    format_contacts_page,
    format_edit_contact_menu,
    format_contact_saved,
    format_optional_context_prompt,
    format_username_not_found,
)
from src.bot.parsers.frequency import format_frequency
from src.db.engine import get_supabase
from src.db.repositories.contacts import ContactRepository
from src.db.repositories.users import UserRepository
from src.services.contact_enrichment import enrich_contact_data
from src.services.telegram_username_service import (
    UsernameValidationUnavailable,
    validate_public_username,
)

USERNAME_PATTERN = re.compile(
    r"^@?([a-zA-Z][a-zA-Z0-9_]{4,31})(?:\s+(.+))?$",
    re.IGNORECASE | re.DOTALL,
)
CONTACTS_PAGE_SIZE = 10
TAG_TOKEN_PATTERN = re.compile(r"#?[A-Za-zА-Яа-яЁё0-9_/-]+")
CLEAR_CONTEXT_VALUES = {"-", "очистить", "без контекста", "убери контекст", "стереть"}
CLEAR_TAGS_VALUES = {"-", "без тегов", "очистить", "убери теги", "стереть"}


def _normalize_lookup_text(value: str | None) -> str:
    """Normalize user-entered contact lookup text for tolerant matching."""
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def _get_contact_matches(contacts: list, query: str) -> list:
    """Match a typed name or username against saved contacts."""
    normalized_query = _normalize_lookup_text(query)
    username_query = normalized_query.lstrip("@")
    query_tokens = [token for token in username_query.split() if token]

    exact_matches = []
    partial_matches = []

    for contact in contacts:
        display_name = _normalize_lookup_text(contact.display_name)
        username = _normalize_lookup_text(contact.username)

        if normalized_query in {display_name, username, f"@{username}"}:
            exact_matches.append(contact)
            continue

        display_name_matches = bool(
            display_name and query_tokens and all(token in display_name for token in query_tokens)
        )
        username_matches = bool(username_query and username_query in username)

        if display_name_matches or username_matches:
            partial_matches.append(contact)

    return exact_matches or partial_matches


def _clear_edit_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear field-specific contact editing state."""
    context.user_data.pop("editing_contact", None)
    context.user_data.pop("editing_field", None)


def _parse_tags_input(text: str) -> list[str] | None:
    """Parse explicit tag input without involving the LLM."""
    normalized_text = " ".join(text.strip().split())
    if not normalized_text:
        return None

    if normalized_text.lower() in CLEAR_TAGS_VALUES:
        return []

    if "#" in normalized_text:
        candidates = TAG_TOKEN_PATTERN.findall(normalized_text)
    elif any(separator in normalized_text for separator in [",", ";", "\n"]):
        candidates = re.split(r"[,;\n]+", normalized_text)
    else:
        parts = normalized_text.split()
        if len(parts) > 3:
            return None
        candidates = parts

    tags: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        clean = candidate.strip().lstrip("#").strip(".,!?;:()[]{}")
        if not clean:
            continue
        tag = f"#{clean}"
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
        if len(tags) >= 5:
            break

    return tags or None


def _merge_contact_tags(existing_tags: list[str] | None, inferred_tags: list[str] | None) -> list[str]:
    """Preserve manual tags while appending new inferred tags without duplicates."""
    merged: list[str] = []
    seen: set[str] = set()

    for source_tags in (existing_tags or [], inferred_tags or []):
        for raw_tag in source_tags:
            clean = raw_tag.strip()
            if not clean:
                continue
            tag = clean if clean.startswith("#") else f"#{clean}"
            key = tag.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(tag)

    return merged


def _format_edit_menu_reminder(contact) -> str:
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


async def save_contact_from_username(
    message,
    telegram_user,
    username: str,
    raw_description: str = "",
    *,
    edit: bool = False,
) -> bool:
    """Create a contact from a username and open reminder setup."""
    user_id = telegram_user.id
    client = await get_supabase()

    user_repo = UserRepository(client)
    await user_repo.get_or_create(
        user_id=user_id,
        username=telegram_user.username,
        first_name=telegram_user.first_name,
    )

    contact_repo = ContactRepository(client)
    existing = await contact_repo.get_by_username(user_id, username)
    if existing:
        text = (
            f"Контакт <b>@{username}</b> уже есть в списке.\n"
            "Открой «👥 Контакты» и нажми «✏️ Изменить», если хочешь обновить карточку."
        )
        if edit:
            await message.edit_text(text, parse_mode="HTML")
        else:
            await message.reply_text(
                text,
                parse_mode="HTML",
                reply_markup=get_main_reply_keyboard(user_id),
            )
        return False

    validation_available = True
    try:
        validation = await validate_public_username(username)
    except UsernameValidationUnavailable:
        validation_available = False
        validation = None

    if validation_available and validation and not validation.exists:
        text = format_username_not_found(username)
        if edit:
            await message.edit_text(text, parse_mode="HTML")
        else:
            await message.reply_text(
                text,
                parse_mode="HTML",
                reply_markup=get_main_reply_keyboard(user_id),
            )
        return False

    enriched = await enrich_contact_data(
        username=username,
        raw_description=raw_description,
        profile=validation,
        fetch_profile_if_missing=validation_available,
    )

    contact = await contact_repo.create(
        user_id=user_id,
        username=username,
        description=enriched.description or None,
        display_name=enriched.display_name,
        tags=enriched.tags,
        birthday_day=enriched.birthday_day,
        birthday_month=enriched.birthday_month,
        birthday_year=enriched.birthday_year,
        reminder_frequency="monthly",
        next_reminder_date=date.today() + timedelta(days=30),
        status="active",
    )

    if edit:
        await message.edit_text(
            format_contact_saved(username),
            parse_mode="HTML",
            reply_markup=get_reminder_type_keyboard(str(contact.id)),
        )
    else:
        await message.reply_text(
            format_contact_saved(username),
            parse_mode="HTML",
            reply_markup=get_reminder_type_keyboard(str(contact.id)),
        )

    return True


async def send_contacts_page(message, contacts: list, page: int = 0, edit: bool = False) -> None:
    """Send or update one page of the contacts browser."""
    total_pages = max(1, (len(contacts) + CONTACTS_PAGE_SIZE - 1) // CONTACTS_PAGE_SIZE)
    safe_page = max(0, min(page, total_pages - 1))
    text = format_contacts_page(contacts, safe_page, CONTACTS_PAGE_SIZE)
    reply_markup = get_contacts_browser_keyboard(contacts, safe_page, CONTACTS_PAGE_SIZE)

    if edit:
        await message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)


async def show_contacts_page_for_user(
    message,
    user_id: int,
    page: int = 0,
    edit: bool = False,
) -> bool:
    """Render the contacts digest for a user and return whether any contacts exist."""
    client = await get_supabase()
    contact_repo = ContactRepository(client)
    contacts = await contact_repo.get_all_for_user(user_id)

    if not contacts:
        text = (
            "👥 <b>Контакты пока пусты</b>\n\n"
            "Нажми <b>«✨ Добавить»</b>, чтобы сохранить первого человека."
        )
        if edit:
            await message.edit_text(text, parse_mode="HTML")
        else:
            await message.reply_text(
                text,
                parse_mode="HTML",
                reply_markup=get_main_reply_keyboard(user_id),
            )
        return False

    await send_contacts_page(message, contacts, page=page, edit=edit)
    return True


async def handle_add_from_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Handle contact creation after the add flow is started.
    Returns True if the message was consumed by the flow.
    """
    text = get_input_text(update, context, strip=True)
    match = USERNAME_PATTERN.match(text)
    if not match:
        await update.message.reply_text(
            "Не смог распознать карточку.\n\n"
            "Пришли одним сообщением:\n"
            "<code>@username</code> или <code>@username короткий контекст</code>\n\n"
            "Примеры:\n"
            "• <code>@ivan</code>\n"
            "• <code>@ivan коллега из маркетинга</code>\n"
            "• <code>@anna подруга из университета</code>\n\n"
            "Или просто перешли сообщение от нужного человека.",
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    username = match.group(1).lower()
    raw_description = (match.group(2) or "").strip()

    context.user_data.pop("awaiting_add", None)

    user_id = update.effective_user.id
    client = await get_supabase()

    user_repo = UserRepository(client)
    await user_repo.get_or_create(
        user_id=user_id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name,
    )

    contact_repo = ContactRepository(client)
    existing = await contact_repo.get_by_username(user_id, username)
    if existing:
        await update.message.reply_text(
            f"Контакт <b>@{username}</b> уже есть в списке.\n"
            "Открой «👥 Контакты» и нажми «✏️ Править», если хочешь обновить карточку.",
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    validation_available = True
    try:
        validation = await validate_public_username(username)
    except UsernameValidationUnavailable:
        validation_available = False
        validation = None

    if validation_available and validation and not validation.exists:
        context.user_data["awaiting_add"] = True
        await update.message.reply_text(
            format_username_not_found(username),
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    if not raw_description:
        context.user_data["pending_contact"] = {
            "username": username,
            "display_name": getattr(validation, "display_name", None) if validation else None,
            "source": "manual_username",
            "awaiting_context_choice": True,
        }
        await update.message.reply_text(
            format_optional_context_prompt(
                username,
                getattr(validation, "display_name", None) if validation else None,
            ),
            parse_mode="HTML",
            reply_markup=get_optional_context_keyboard(),
        )
        return True

    enriched = await enrich_contact_data(
        username=username,
        raw_description=raw_description,
        profile=validation,
        fetch_profile_if_missing=validation_available,
    )

    contact = await contact_repo.create(
        user_id=user_id,
        username=username,
        description=enriched.description or None,
        display_name=enriched.display_name,
        tags=enriched.tags,
        birthday_day=enriched.birthday_day,
        birthday_month=enriched.birthday_month,
        birthday_year=enriched.birthday_year,
        reminder_frequency="monthly",
        next_reminder_date=date.today() + timedelta(days=30),
        status="active",
    )

    await update.message.reply_text(
        format_contact_saved(username),
        parse_mode="HTML",
        reply_markup=get_reminder_type_keyboard(str(contact.id)),
    )
    return True


async def handle_list_contacts(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show contacts as a paginated inline browser."""
    user_id = update.effective_user.id
    context.user_data.pop("awaiting_contact_lookup", None)
    context.user_data.pop("contact_list_page", None)
    await show_contacts_page_for_user(update.message, user_id, page=0)


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start the add-contact flow."""
    context.user_data["awaiting_add"] = True

    await update.message.reply_text(
        "✨ <b>Новый контакт</b>\n\n"
        "Отправь одним сообщением:\n"
        "<code>@username</code> или <code>@username короткий контекст</code>\n\n"
        "Примеры:\n"
        "• <code>@ivan</code>\n"
        "• <code>@ivan коллега из маркетинга</code>\n"
        "• <code>@anna подруга детства</code>\n"
        "• <code>@peter партнёр по бизнесу</code>\n\n"
        "Следом я предложу выбрать частоту напоминаний.\n"
        "Если удобнее, можно просто переслать сообщение человека.",
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard(update.effective_user.id),
    )


async def handle_edit_from_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Handle a field-specific edit request for the selected contact.
    Returns True if the message was consumed by the flow.
    """
    from uuid import UUID

    contact_id_str = context.user_data.get("editing_contact")
    if not contact_id_str:
        return False

    editing_field = context.user_data.get("editing_field")
    text = get_input_text(update, context, strip=True) or ""
    user_id = update.effective_user.id

    client = await get_supabase()
    contact_repo = ContactRepository(client)
    contact = await contact_repo.get_by_id(UUID(contact_id_str))

    if not contact or contact.user_id != user_id:
        _clear_edit_state(context)
        await update.message.reply_text(
            "Не нашёл эту карточку. Попробуй открыть контакт заново.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    if not editing_field:
        _clear_edit_state(context)
        await update.message.reply_text(
            "Сначала выбери, что именно нужно поменять, кнопкой «✏️ Править» в карточке.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    if editing_field == "reminder":
        await update.message.reply_text(
            "Для напоминаний выбери формат и частоту inline-кнопками в меню редактирования.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    if editing_field == "description":
        new_description = None if text.lower() in CLEAR_CONTEXT_VALUES else text
        updates = {"description": new_description}
        auto_tags_added = False
        if new_description:
            enriched = await enrich_contact_data(
                username=contact.username,
                raw_description=new_description,
                suggested_display_name=contact.display_name,
                fetch_profile_if_missing=False,
            )
            updates["description"] = enriched.description or new_description
            merged_tags = _merge_contact_tags(contact.tags, enriched.tags)
            if merged_tags != (contact.tags or []):
                updates["tags"] = merged_tags
                auto_tags_added = bool(enriched.tags)

        await contact_repo.update(contact.id, **updates)
        _clear_edit_state(context)
        confirmation_text = f"✅ Контекст для <b>@{contact.username}</b> обновил."
        if auto_tags_added:
            confirmation_text += " Новые теги из контекста добавил автоматически."
        await update.message.reply_text(
            confirmation_text,
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
    elif editing_field == "tags":
        new_tags = _parse_tags_input(text)
        if new_tags is None:
            await update.message.reply_text(
                "Не смог разобрать теги.\n"
                "Пришли их видом <code>#работа #друзья</code> или <code>работа, друзья</code>.",
                parse_mode="HTML",
                reply_markup=get_main_reply_keyboard(update.effective_user.id),
            )
            return True

        await contact_repo.update(contact.id, tags=new_tags)
        _clear_edit_state(context)
        await update.message.reply_text(
            f"✅ Теги для <b>@{contact.username}</b> обновил.",
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
    else:
        _clear_edit_state(context)
        await update.message.reply_text(
            "Не понял, что именно нужно поменять. Открой редактирование заново.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    updated_contact = await contact_repo.get_by_id(contact.id)
    from src.bot.handlers.callbacks import send_contact_card

    await send_contact_card(update.message, updated_contact)

    return True


async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fallback slash-command handler for editing a contact by username."""
    if context.args:
        username = context.args[0].lstrip("@")
        user_id = update.effective_user.id

        client = await get_supabase()
        contact_repo = ContactRepository(client)
        contact = await contact_repo.get_by_username(user_id, username)

        if not contact:
            await update.message.reply_text(
                f"Контакт @{username} не найден.",
                reply_markup=get_main_reply_keyboard(update.effective_user.id),
            )
            return

        await update.message.reply_text(
            format_edit_contact_menu(
                contact.username,
                contact.description,
                contact.tags,
                _format_edit_menu_reminder(contact),
            ),
            parse_mode="HTML",
            reply_markup=get_contact_edit_keyboard(str(contact.id)),
        )
    else:
        await update.message.reply_text(
            "✏️ <b>Редактирование контакта</b>\n\n"
            "Открой «👥 Контакты» и нажми «✏️ Править» у нужного человека.",
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start the semantic-search flow."""
    if context.args:
        query = " ".join(context.args)
        context.user_data["search_query"] = query
        from src.bot.handlers.search import perform_search

        await perform_search(update, context, query)
    else:
        context.user_data["awaiting_search"] = True
        await update.message.reply_text(
            "🔎 <b>Поиск по контактам</b>\n\n"
            "Напиши обычным языком, кого или по какому контексту ищешь.\n\n"
            "Примеры:\n"
            "• <code>кто работает в IT?</code>\n"
            "• <code>контакты из Москвы</code>\n"
            "• <code>друзья</code>",
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )


async def handle_contact_lookup_from_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Open a contact card when the user types a name after opening the contacts list.
    Returns True if the message was consumed by the list-selection flow.
    """
    if not context.user_data.get("awaiting_contact_lookup"):
        return False

    text = get_input_text(update, context, strip=True) or ""
    if not text:
        return True

    user_id = update.effective_user.id
    client = await get_supabase()
    contact_repo = ContactRepository(client)
    contacts = await contact_repo.get_all_for_user(user_id)

    if not contacts:
        context.user_data.pop("awaiting_contact_lookup", None)
        context.user_data.pop("contact_list_page", None)
        await update.message.reply_text(
            "👥 <b>Контакты пока пусты</b>\n\n"
            "Нажми <b>«✨ Добавить»</b>, чтобы сохранить первого человека.",
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    matches = _get_contact_matches(contacts, text)
    if not matches:
        await update.message.reply_text(
            format_contact_lookup_not_found(text),
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    if len(matches) > 1:
        await update.message.reply_text(
            format_contact_lookup_ambiguous(text, matches),
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    context.user_data.pop("awaiting_contact_lookup", None)
    context.user_data.pop("contact_list_page", None)

    from src.bot.handlers.callbacks import send_contact_card

    await send_contact_card(update.message, matches[0])
    return True


def get_contact_handlers() -> list:
    """Slash commands are intentionally disabled in the user-facing UX."""
    return []
