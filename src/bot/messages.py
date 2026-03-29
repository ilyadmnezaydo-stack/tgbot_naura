"""
User-facing message templates.
"""
from datetime import date, datetime
from html import escape

import pytz


def _truncate(text: str, limit: int = 160) -> str:
    """Keep long note previews compact inside cards."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _format_identity(username: str, display_name: str | None = None) -> str:
    """Format the main contact identity block."""
    safe_username = escape(username)
    if display_name:
        safe_name = escape(display_name)
        return f"<b>{safe_name}</b>\n<code>@{safe_username}</code>"
    return f"<b>@{safe_username}</b>"


def format_birthday(day: int | None, month: int | None, year: int | None = None) -> str | None:
    """Format a partial or full birthday for UI output."""
    if not day or not month:
        return None
    if year:
        return f"{day:02d}.{month:02d}.{year}"
    return f"{day:02d}.{month:02d}"


def format_birthday_badge(
    day: int | None,
    month: int | None,
    year: int | None = None,
    *,
    today: date | None = None,
) -> str | None:
    """Format birthday text, including age on the birthday itself when possible."""
    birthday_text = format_birthday(day, month, year)
    if not birthday_text:
        return None

    if year and today and year <= today.year and today.month == month and today.day == day:
        return f"{birthday_text} • {today.year - year} лет"

    return birthday_text


def format_contact_preview(
    username: str,
    description: str,
    tags: list[str],
    display_name: str | None = None,
    birthday_day: int | None = None,
    birthday_month: int | None = None,
    birthday_year: int | None = None,
) -> str:
    """Format the draft preview before saving a contact."""
    safe_desc = escape(description) if description else ""
    tags_text = " ".join(tags) if tags else ""
    safe_tags = escape(tags_text) if tags_text else ""
    sections = [
        "📇 <b>Проверь новую карточку</b>",
        _format_identity(username, display_name),
        f"<b>Контекст</b>\n{safe_desc or 'Пока без описания.'}",
        f"<b>Теги</b>\n{safe_tags or 'Без тегов'}",
    ]
    birthday_text = format_birthday(birthday_day, birthday_month, birthday_year)
    if birthday_text:
        sections.append(f"<b>День рождения</b>\n{escape(birthday_text)}")
    sections.append("Если всё выглядит хорошо, можно сохранять.")
    return "\n\n".join(sections)


def format_contact_saved(username: str) -> str:
    """Format the message shown after a contact is saved."""
    return (
        "✅ <b>Контакт сохранён</b>\n\n"
        f"<code>@{escape(username)}</code> уже в списке.\n"
        "Теперь выбери: регулярную частоту напоминаний, разовую дату или пока сохранить без напоминаний."
    )


def format_reminder_set(username: str, frequency_text: str, next_date_str: str) -> str:
    """Format the message shown after a reminder is configured."""
    return (
        "🔔 <b>Частота напоминаний настроена</b>\n\n"
        f"<code>@{escape(username)}</code>\n"
        f"Режим: {escape(frequency_text)}\n"
        f"Ближайшее напоминание: {next_date_str}"
    )


def format_no_reminder_set(username: str) -> str:
    """Format the message shown when the user opts out of reminders."""
    return (
        "🌙 <b>Сохранил без напоминаний</b>\n\n"
        f"<code>@{escape(username)}</code> уже в списке.\n"
        "Когда захочешь, частоту напоминаний можно настроить прямо из карточки."
    )


def format_contact_card(
    username: str,
    description: str | None,
    tags: list[str] | None,
    status: str,
    next_reminder_date,
    one_time_date,
    prefix: str = "",
    display_name: str | None = None,
    last_note: str | None = None,
    birthday_day: int | None = None,
    birthday_month: int | None = None,
    birthday_year: int | None = None,
) -> str:
    """Format a contact card with safe HTML escaping."""
    if status == "paused":
        status_text = "Пауза. Напоминания выключены."
    elif status == "one_time":
        date_str = (
            one_time_date.strftime("%d.%m.%Y")
            if one_time_date
            else next_reminder_date.strftime("%d.%m.%Y") if next_reminder_date else "?"
        )
        status_text = f"Разовое напоминание: {date_str}"
    else:
        next_date = next_reminder_date.strftime("%d.%m.%Y") if next_reminder_date else "?"
        status_text = (
            f"Следующее напоминание: {next_date}"
            if next_reminder_date
            else "Частота напоминаний сохранена, но дата пока не рассчитана."
        )

    safe_desc = escape(description) if description else ""
    tags_text = " ".join(tags) if tags else ""
    safe_tags = escape(tags_text) if tags_text else ""
    safe_note = escape(_truncate(last_note)) if last_note else ""
    sections = []
    if prefix:
        sections.append(prefix.rstrip())
    sections.extend(
        [
            "📇 <b>Карточка контакта</b>",
            _format_identity(username, display_name),
            f"<b>Контекст</b>\n{safe_desc or 'Пока без описания.'}",
            f"<b>Теги</b>\n{safe_tags or 'Без тегов'}",
        ]
    )
    birthday_text = format_birthday(birthday_day, birthday_month, birthday_year)
    if birthday_text:
        sections.append(f"<b>День рождения</b>\n{escape(birthday_text)}")
    if safe_note:
        sections.append(f"<b>Последняя заметка</b>\n{safe_note}")
    sections.append(f"<b>Частота напоминаний</b>\n{status_text}")
    return "\n\n".join(sections)


def _format_contact_list_status(status: str, next_reminder_date, one_time_date) -> str:
    """Format a short status line for the paginated contacts list."""
    if status == "paused":
        return "на паузе"

    if status == "one_time":
        reminder_date = one_time_date or next_reminder_date
        if reminder_date:
            return f"разовое напоминание: {reminder_date.strftime('%d.%m.%Y')}"
        return "разовое напоминание"

    if next_reminder_date:
        return f"следующее напоминание: {next_reminder_date.strftime('%d.%m.%Y')}"
    return "напоминание пока не настроено"


def _has_distinct_display_name(contact) -> bool:
    """Return True when the saved display name adds value beyond the username."""
    if not getattr(contact, "display_name", None):
        return False
    return contact.display_name.strip().lower() != (contact.username or "").strip().lower()


def format_contacts_page(contacts: list, page: int, page_size: int) -> str:
    """Format one page of contacts for the inline browser."""
    total_contacts = len(contacts)
    total_pages = max(1, (total_contacts + page_size - 1) // page_size)
    safe_page = max(0, min(page, total_pages - 1))
    start_index = safe_page * page_size
    page_contacts = contacts[start_index : start_index + page_size]

    lines = [
        "👥 <b>Контакты</b>",
        f"Всего: {total_contacts} • страница {safe_page + 1}/{total_pages}",
        "",
    ]

    for number, contact in enumerate(page_contacts, start=start_index + 1):
        has_name = _has_distinct_display_name(contact)
        title = escape(contact.display_name) if has_name else f"@{contact.username}"
        username_suffix = f" (@{contact.username})" if has_name else ""
        description = (
            escape(_truncate(contact.description, limit=90))
            if contact.description
            else "Пока без описания."
        )
        status_text = _format_contact_list_status(
            contact.status,
            contact.next_reminder_date,
            contact.one_time_date,
        )

        lines.append(f"{number}. <b>{title}</b>{username_suffix}")
        lines.append(f"Контекст: {description}")
        lines.append(f"Статус: {status_text}")
        lines.append("")

    lines.extend(
        [
            "Открывай карточку кнопками ниже.",
            "Страницы листаются через «Назад» и «След».",
        ]
    )
    return "\n".join(lines)


def format_contact_lookup_not_found(query: str) -> str:
    """Explain that no contact matched the typed lookup query."""
    safe_query = escape(query)
    return (
        f"Не нашёл точного совпадения по запросу <b>{safe_query}</b>.\n\n"
        "Попробуй отправить полное имя из списка или <code>@username</code>."
    )


def format_contact_lookup_ambiguous(query: str, contacts: list) -> str:
    """Ask the user to уточнить contact when several matches were found."""
    safe_query = escape(query)
    lines = [
        f"Нашёл несколько похожих карточек по запросу <b>{safe_query}</b>.",
        "",
        "Уточни имя или <code>@username</code>:",
    ]

    for contact in contacts[:5]:
        if _has_distinct_display_name(contact):
            safe_name = escape(contact.display_name)
            lines.append(f"• <b>{safe_name}</b> (@{contact.username})")
        else:
            lines.append(f"• <b>@{contact.username}</b>")

    if len(contacts) > 5:
        lines.append("• …")

    return "\n".join(lines)


def format_existing_contact_found(username: str) -> str:
    """Format the message shown when a forwarded contact already exists."""
    return (
        f"📇 <b>@{escape(username)}</b> уже есть в контактах.\n\n"
        "Можно обновить контекст, поменять частоту напоминаний или удалить карточку."
    )


def format_custom_interval_prompt() -> str:
    """Prompt for a custom reminder interval."""
    return (
        "⏱ <b>Своя частота напоминаний</b>\n\n"
        "Напиши число дней от 1 до 365.\n"
        "Например: <code>45</code>\n\n"
        "Я буду автоматически считать следующую дату после каждого отмеченного контакта."
    )


def format_custom_date_prompt() -> str:
    """Prompt for a custom one-time reminder date."""
    return (
        "📅 <b>Разовое напоминание</b>\n\n"
        "Напиши дату в удобном формате:\n\n"
        "• <code>завтра</code>\n"
        "• <code>через неделю</code>\n"
        "• <code>в пятницу</code>\n"
        "• <code>15 апреля</code>\n"
        "• <code>25.04.2026</code>"
    )


def format_optional_context_prompt(username: str, display_name: str | None = None) -> str:
    """Ask whether the user wants to add context for a new contact now."""
    identity_lines = []
    if display_name:
        identity_lines.append(escape(display_name))
    identity_lines.append(f"@{escape(username)}")
    identity_block = "\n".join(identity_lines)

    return (
        "📇 <b>Новый контакт</b>\n\n"
        f"{identity_block}\n\n"
        "Можно сразу добавить короткий контекст, чтобы потом было легче вспомнить человека.\n"
        "Например: <code>коллега из маркетинга</code>\n\n"
        "Если не хочется сейчас, это нормально: контекст можно добавить позже из карточки контакта."
    )


def format_description_prompt(username: str, display_name: str | None) -> str:
    """Prompt for a contact context."""
    return (
        "📇 <b>Добавим контекст для контакта</b>\n\n"
        f"{_format_identity(username, display_name)}\n\n"
        "Напиши 1-2 фразы, чтобы потом быстро вспомнить, кто это и почему человек важен.\n"
        "Например: <code>дизайнер, познакомились на митапе</code>\n"
        "Теги я подтяну автоматически из этого контекста.\n\n"
        "Если не хочется сейчас, контекст можно добавить позже из карточки контакта."
    )


def format_edit_description_prompt(username: str) -> str:
    """Prompt for an updated contact context."""
    return (
        f"✏️ <b>Обновим контекст @{escape(username)}</b>\n\n"
        "Пришли новое описание одним сообщением.\n\n"
        "Например: <code>коллега из маркетинга, познакомились на конференции</code>\n"
        "Новые теги из этого контекста я добавлю автоматически, а уже сохранённые не потеряю.\n"
        "Если хочешь очистить контекст, можно написать <code>-</code>."
    )


def format_edit_tags_prompt(username: str) -> str:
    """Prompt for updated tags."""
    return (
        f"🏷 <b>Обновим теги @{escape(username)}</b>\n\n"
        "Пришли теги одним сообщением.\n\n"
        "Подойдут варианты:\n"
        "• <code>#работа #друзья</code>\n"
        "• <code>работа, друзья</code>\n\n"
        "Если хочешь убрать теги совсем, напиши <code>без тегов</code> или <code>-</code>."
    )


def format_edit_contact_menu(
    username: str,
    description: str | None,
    tags: list[str] | None,
    reminder_text: str,
) -> str:
    """Show the edit menu with the current contact values."""
    safe_desc = escape(description) if description else ""
    tags_text = " ".join(tags) if tags else ""
    safe_tags = escape(tags_text) if tags_text else ""
    return (
        f"✏️ <b>Что поменять у @{escape(username)}?</b>\n\n"
        f"<b>Контекст</b>\n{safe_desc or 'Пока без описания.'}\n\n"
        f"<b>Теги</b>\n{safe_tags or 'Без тегов'}\n\n"
        f"<b>Напоминания</b>\n{escape(reminder_text)}"
    )


def format_contact_note_prompt(username: str) -> str:
    """Prompt for a short post-contact note."""
    return (
        "💬 <b>Контакт уже отмечен</b>\n\n"
        f"Если хочешь, добавь короткую заметку по <b>@{escape(username)}</b>, чтобы потом быстро вспомнить контекст разговора.\n\n"
        "Например: <code>обсудили созвон на следующей неделе</code>\n\n"
        "Можно отправить заметку текстом или голосовым сообщением, либо нажать «Пропустить».\n"
        "Все заметки будут доступны в разделе <b>«📝 Заметки»</b>."
    )


def format_contact_note_saved(username: str) -> str:
    """Confirm that a post-contact note was saved."""
    return (
        f"💬 Контакт с <b>@{escape(username)}</b> отмечен, заметка сохранена.\n"
        "Она уже доступна в разделе <b>«📝 Заметки»</b>."
    )


def format_contact_note_skipped(username: str) -> str:
    """Confirm that the user skipped the note step."""
    return f"Ок, контакт с <b>@{escape(username)}</b> отмечен, заметку не добавляю."


def _notes_range_label(date_range: str) -> str:
    """Format human-readable label for notes date filters."""
    labels = {
        "all": "все даты",
        "today": "сегодня",
        "week": "последние 7 дней",
        "month": "последние 30 дней",
    }
    return labels.get(date_range, "все даты")


def _notes_order_label(order: str) -> str:
    """Format human-readable label for notes ordering."""
    return "сначала новые" if order == "new" else "сначала старые"


def _format_note_contact_title(contact) -> str:
    """Format the contact title shown in the notes list."""
    if not contact:
        return "Контакт удалён"

    if _has_distinct_display_name(contact):
        safe_name = escape(contact.display_name)
        return f"{safe_name} (@{contact.username})"

    return f"@{contact.username}"


def _format_note_datetime(value: datetime, timezone_name: str) -> str:
    """Format note datetime in the project timezone."""
    if value.tzinfo:
        normalized = value.astimezone(pytz.timezone(timezone_name))
        return normalized.strftime("%d.%m.%Y %H:%M")
    return value.strftime("%d.%m.%Y %H:%M")


def format_notes_empty(has_saved_notes: bool, date_range: str = "all") -> str:
    """Format empty-state message for the dedicated notes section."""
    if not has_saved_notes:
        return (
            "📝 <b>Заметки</b>\n\n"
            "Пока здесь пусто.\n"
            "После общения можно отметить контакт и сохранить короткий итог разговора, и он появится здесь."
        )

    return (
        "📝 <b>Заметки</b>\n\n"
        f"По фильтру <b>{_notes_range_label(date_range)}</b> заметок пока нет.\n"
        "Попробуй сменить период или сортировку."
    )


def format_notes_page(
    notes: list,
    contacts_by_id: dict[str, object],
    date_range: str,
    order: str,
    page: int,
    total_pages: int,
    total_notes: int,
    start_index: int,
    timezone_name: str,
) -> str:
    """Format one page of saved notes for browsing."""
    lines = [
        "📝 <b>Заметки</b>",
        (
            f"Фильтр: {_notes_range_label(date_range)} • "
            f"Сортировка: {_notes_order_label(order)} • "
            f"Страница {page + 1}/{total_pages}"
        ),
        f"Всего в выдаче: {total_notes}",
        "",
    ]

    for number, note in enumerate(notes, start=start_index + 1):
        contact = contacts_by_id.get(note.contact_id)
        title = _format_note_contact_title(contact)
        note_dt = _format_note_datetime(note.created_at, timezone_name)
        safe_text = escape(_truncate(note.text, limit=220))

        lines.append(f"{number}. <b>{title}</b>")
        lines.append(f"🕒 {note_dt}")
        lines.append(safe_text)
        lines.append("")

    lines.append("Фильтры ниже помогут быстро перелистывать заметки по периоду.")
    return "\n".join(lines)


def format_owner_dashboard_access_denied() -> str:
    """Tell non-owner users that the analytics dashboard is unavailable."""
    return "Этот дашборд доступен только администраторам бота."


def format_owner_dashboard(
    total_users: int,
    active_users: int,
    total_contacts: int,
    active_contacts: int,
    top_buttons: list,
    owner_is_restricted: bool,
) -> str:
    """Format the owner analytics dashboard."""
    lines = [
        "📊 <b>Дашборд владельца</b>",
        "",
        f"👤 Всего пользователей в боте: <b>{total_users}</b>",
        f"🟢 Активные за 7 дней: <b>{active_users}</b>",
        f"👥 Всего контактов в базе: <b>{total_contacts}</b>",
        f"🔔 Активные контакты: <b>{active_contacts}</b>",
        "",
        "<b>Какие кнопки нажимают чаще всего</b>",
    ]

    if top_buttons:
        for index, button in enumerate(top_buttons, start=1):
            lines.append(f"{index}. {escape(button.label)} — {button.count}")
    else:
        lines.append("Пока нет данных по нажатиям. Они начнут собираться после включения аналитики.")

    lines.extend(
        [
            "",
            "Активность считается по взаимодействиям пользователей с ботом за последние 7 дней.",
            (
                "Дашборд ограничен по `OWNER_USER_ID`."
                if owner_is_restricted
                else "Сейчас `OWNER_USER_ID` не задан, поэтому доступ к дашборду не ограничен через env."
            ),
        ]
    )
    return "\n".join(lines)


def format_donation_intro() -> str:
    """Introduce the Telegram Stars donation flow."""
    return (
        "⭐ <b>Поддержать проект</b>\n\n"
        "Если бот помогает не терять связь с людьми, можно поддержать его развитие через Telegram Stars или оплатой по СБП.\n"
        "Ниже можно выбрать удобный способ.\n\n"
        "Если понадобится помощь с оплатой, просто отправь <code>/paysupport</code>."
    )


def format_donation_custom_prompt() -> str:
    """Prompt the user for a custom Telegram Stars amount."""
    return (
        "⭐ <b>Своя сумма поддержки</b>\n\n"
        "Пришли одним сообщением, сколько Stars хочешь отправить.\n"
        "Подойдут варианты вроде <code>777</code>, <code>1 000</code> или <code>777 ⭐</code>.\n\n"
        "Можно указать любое целое число больше нуля.\n"
        "Если передумаешь, напиши <code>отмена</code>."
    )


def format_donation_amount_invalid() -> str:
    """Explain how to enter a valid custom Stars amount."""
    return (
        "Не смог разобрать сумму.\n\n"
        "Пришли целое число Stars, например <code>250</code> или <code>1 000 ⭐</code>."
    )


def format_cloudpayments_amount_prompt() -> str:
    """Prompt the user for a custom SBP amount in RUB."""
    return (
        "🏦 <b>Оплата по СБП</b>\n\n"
        "Пришли сумму в рублях одним сообщением.\n"
        "Подойдут варианты вроде <code>500</code>, <code>1 500</code> или <code>1499,90 ₽</code>.\n\n"
        "Если передумаешь, напиши <code>отмена</code>."
    )


def format_cloudpayments_amount_invalid() -> str:
    """Explain how to enter a valid SBP amount."""
    return (
        "Не смог разобрать сумму для СБП.\n\n"
        "Пришли число в рублях, например <code>500</code> или <code>1499,90 ₽</code>."
    )


def format_cloudpayments_link_ready(amount, currency: str = "RUB") -> str:
    """Tell the user the SBP payment link is ready."""
    currency_label = "₽" if currency.upper() == "RUB" else currency.upper()
    return (
        f"🏦 Ссылка на оплату готова.\n\n"
        f"Сумма: <b>{amount} {currency_label}</b>\n"
        "Открой кнопку ниже и оплати через СБП.\n"
        "После успешной оплаты я сам пришлю подтверждение в этот чат."
    )


def format_cloudpayments_unavailable() -> str:
    """Explain that CloudPayments isn't configured yet."""
    return (
        "СБП-оплата сейчас недоступна на стороне бота.\n"
        "Нужно заполнить настройки CloudPayments и поднять webhook API."
    )


def format_cloudpayments_success(*, amount, currency: str = "RUB") -> str:
    """Thank the user for a successful CloudPayments SBP payment."""
    currency_label = "₽" if currency.upper() == "RUB" else currency.upper()
    return (
        f"✅ Оплата по СБП прошла успешно.\n\n"
        f"Получил <b>{amount} {currency_label}</b>. Спасибо за поддержку проекта."
    )


def format_donation_invoice_sent(amount: int) -> str:
    """Tell the user that the Stars invoice is ready."""
    return (
        f"⭐ Готово. Ниже отправил счёт на <b>{amount} Stars</b>.\n"
        "Оплата проходит прямо внутри Telegram."
    )


def format_donation_success(amount: int) -> str:
    """Thank the user for a successful Stars donation."""
    return (
        f"Спасибо за поддержку на <b>{amount} Stars</b>.\n"
        "Это помогает развивать бота и делать сценарии ещё удобнее."
    )


def format_paysupport_text() -> str:
    """Payment support instructions required for Telegram payments."""
    return (
        "💳 <b>Поддержка по оплате</b>\n\n"
        "Если возник вопрос по донату через Stars, напиши сюда в этот чат:\n"
        "• дату и примерное время платежа\n"
        "• сумму в Stars\n"
        "• при необходимости приложи скрин\n\n"
        "Я сохраню идентификаторы платежа, чтобы при необходимости можно было проверить оплату вручную."
    )


def format_support_prompt() -> str:
    """Prompt the user to send a support question."""
    return (
        "💬 <b>Поддержка</b>\n\n"
        "Напиши вопрос одним сообщением.\n"
        "Сначала попробует помочь AI-поддержка, а если вопрос сложный, я передам его человеку."
    )


def format_support_ai_answer(answer: str) -> str:
    """Format the first-line AI support answer."""
    safe_answer = escape(answer)
    return (
        "🤖 <b>AI-поддержка</b>\n\n"
        f"{safe_answer}\n\n"
        "Если останется непонятно, можно снова открыть поддержку из раздела помощи."
    )


def format_support_escalated() -> str:
    """Confirm that the question was escalated to a human."""
    return (
        "📨 <b>Вопрос передан админу</b>\n\n"
        "Как только человек ответит, я пришлю сообщение сюда."
    )


def format_support_no_admins() -> str:
    """Explain that human escalation is currently unavailable."""
    return (
        "💬 Вопрос выглядит сложным, но сейчас живая поддержка не настроена.\n\n"
        "Попробуй позже или проверь, заданы ли `OWNER_USER_ID` или `ADMIN_USER_IDS` у бота."
    )


def format_support_followup_prompt() -> str:
    """Ask the user for a follow-up after an admin answer."""
    return (
        "✉️ Напиши, что осталось непонятным.\n"
        "Я передам это админу как продолжение вопроса."
    )


def format_support_user_answer(answer: str) -> str:
    """Format the admin answer delivered back to the user."""
    safe_answer = escape(answer)
    return (
        "💬 <b>Ответ поддержки</b>\n\n"
        f"{safe_answer}\n\n"
        "Если всё ок, нажми «Помогло, спасибо». Если нет, можно задать уточнение."
    )


def format_support_feedback_thanks() -> str:
    """Thank the user for confirming that the answer helped."""
    return "Спасибо за обратную связь. Если понадобится, поддержка всегда рядом."


def format_support_admin_ticket(ticket) -> str:
    """Format the support question delivered to the admin."""
    username = f"@{escape(ticket.user_username)}" if ticket.user_username else "без username"
    first_name = escape(ticket.user_first_name) if ticket.user_first_name else "Без имени"
    source_label = "Уточнение" if getattr(ticket, "source", "initial") == "followup" else "Новый вопрос"
    short_id = escape(ticket.id[:8])
    safe_question = escape(ticket.question)

    return (
        f"📨 <b>{source_label} в поддержку</b>\n\n"
        f"<b>Тикет</b>: <code>{short_id}</code>\n"
        f"<b>Пользователь</b>: {first_name} ({username})\n"
        f"<b>ID</b>: <code>{ticket.user_id}</code>\n\n"
        f"<b>Вопрос</b>\n{safe_question}"
    )


def format_support_admin_reply_prompt(ticket) -> str:
    """Prompt the admin to write a reply."""
    short_id = escape(ticket.id[:8])
    return (
        f"✍️ <b>Ответ для тикета {short_id}</b>\n\n"
        "Пришли одним сообщением текст, который нужно отправить пользователю."
    )


def format_support_admin_skip() -> str:
    """Confirm that the admin skipped the support ticket."""
    return "Ок, вопрос пока оставил без ответа."


def format_username_not_found(username: str) -> str:
    """Format the message shown when a Telegram username does not exist."""
    return (
        f"Не нашёл <b>@{escape(username)}</b> в Telegram.\n\n"
        "Проверь написание или просто перешли мне сообщение от этого человека."
    )


def format_username_validation_unavailable() -> str:
    """Format the message shown when username validation is temporarily unavailable."""
    return (
        "Сейчас не получилось проверить username в Telegram.\n\n"
        "Попробуй ещё раз чуть позже или добавь контакт через пересланное сообщение."
    )
