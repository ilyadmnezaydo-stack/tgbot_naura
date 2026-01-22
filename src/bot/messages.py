"""
Message templates for the bot.
All user-facing message texts are defined here for consistency.
Uses HTML parse mode for reliable formatting (no issues with underscores in usernames).
"""
from html import escape


def format_contact_preview(
    username: str, description: str, tags: list[str], display_name: str | None = None
) -> str:
    """Format contact preview before confirmation."""
    safe_desc = escape(description) if description else ""
    tags_text = " ".join(tags) if tags else ""
    safe_tags = escape(tags_text) if tags_text else ""

    text = "📇 <b>Новый контакт:</b>\n\n"
    if display_name:
        safe_name = escape(display_name)
        text += f"<b>{safe_name}</b> (@{username})\n"
    else:
        text += f"<b>@{username}</b>\n"
    if safe_desc:
        text += f"{safe_desc}\n"
    if safe_tags:
        text += f"\n{safe_tags}"

    return text


def format_contact_saved(username: str) -> str:
    """Format message after contact is saved."""
    return f"✅ Контакт <b>@{username}</b> сохранен!\n\nВыбери тип напоминания:"


def format_reminder_set(username: str, frequency_text: str, next_date_str: str) -> str:
    """Format message after reminder is set."""
    return (
        f"🔔 Готово!\n\n"
        f"<b>@{username}</b>\n"
        f"Напоминание: {frequency_text}\n"
        f"Следующее: {next_date_str}"
    )


def format_no_reminder_set(username: str) -> str:
    """Format message when no reminder is set."""
    return f"✅ Контакт <b>@{username}</b> сохранен без напоминания."


def format_contact_card(
    username: str,
    description: str | None,
    tags: list[str] | None,
    status: str,
    next_reminder_date,
    one_time_date,
    prefix: str = "",
    display_name: str | None = None,
) -> str:
    """Format contact card text with HTML escaping."""
    # Format status/date info
    if status == "paused":
        status_text = "⏸️ На паузе"
    elif status == "one_time":
        date_str = (
            one_time_date.strftime("%d.%m")
            if one_time_date
            else next_reminder_date.strftime("%d.%m") if next_reminder_date else "?"
        )
        status_text = f"📅 Напоминание: {date_str}"
    else:
        next_date = next_reminder_date.strftime("%d.%m") if next_reminder_date else "?"
        status_text = f"🔔 Следующее: {next_date}"

    tags_text = " ".join(tags) if tags else ""
    desc_text = description or ""

    # Escape HTML in user-provided text
    safe_desc = escape(desc_text) if desc_text else ""
    safe_tags = escape(tags_text) if tags_text else ""

    # Build card: name/username, description, tags, status
    if display_name:
        safe_name = escape(display_name)
        text = f"{prefix}<b>{safe_name}</b> (@{username})\n"
    else:
        text = f"{prefix}<b>@{username}</b>\n"
    if safe_desc:
        text += f"{safe_desc}\n"
    if safe_tags:
        text += f"{safe_tags}\n"
    text += status_text

    return text


def format_existing_contact_found(username: str) -> str:
    """Format message when user re-forwards an existing contact."""
    return f"📇 <b>@{username}</b> уже в твоих контактах.\n\nЧто хочешь сделать?"


def format_custom_interval_prompt() -> str:
    """Format prompt for custom interval input."""
    return (
        "Введи интервал в днях (число от 1 до 365):\n\n"
        "Например: <code>45</code> — напоминание раз в 45 дней"
    )


def format_custom_date_prompt() -> str:
    """Format prompt for custom date input."""
    return (
        "Когда напомнить? Напиши дату в любом формате:\n\n"
        "• <code>завтра</code>\n"
        "• <code>через неделю</code>\n"
        "• <code>в пятницу</code>\n"
        "• <code>15 февраля</code>\n"
        "• <code>25.02.2025</code>"
    )


def format_description_prompt(username: str, display_name: str) -> str:
    """Format prompt for contact description."""
    safe_display_name = escape(display_name)
    return (
        f"📇 <b>{safe_display_name}</b> (@{username})\n\n"
        f"Напиши описание:\n"
        f"<code>коллега из IT</code>\n\n"
        f"Или /cancel для отмены."
    )


def format_edit_description_prompt(username: str) -> str:
    """Format prompt for editing contact description."""
    return (
        f"✏️ Редактирование <b>@{username}</b>\n\n"
        f"Отправь новое описание контакта:"
    )
