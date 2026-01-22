"""
Message templates for the bot.
All user-facing message texts are defined here for consistency.
"""
from telegram.helpers import escape_markdown


def format_contact_preview(
    username: str, description: str, tags: list[str], display_name: str | None = None
) -> str:
    """Format contact preview before confirmation."""
    safe_desc = escape_markdown(description, version=1) if description else ""
    tags_text = " ".join(tags) if tags else ""
    safe_tags = escape_markdown(tags_text, version=1) if tags_text else ""

    text = f"📇 *Новый контакт:*\n\n"
    if display_name:
        safe_name = escape_markdown(display_name, version=1)
        text += f"*{safe_name}* (@{username})\n"
    else:
        text += f"*@{username}*\n"
    if safe_desc:
        text += f"{safe_desc}\n"
    if safe_tags:
        text += f"\n{safe_tags}"

    return text


def format_contact_saved(username: str) -> str:
    """Format message after contact is saved."""
    return f"✅ Контакт *@{username}* сохранен!\n\nВыбери тип напоминания:"


def format_reminder_set(username: str, frequency_text: str, next_date_str: str) -> str:
    """Format message after reminder is set."""
    return (
        f"🔔 Готово!\n\n"
        f"*@{username}*\n"
        f"Напоминание: {frequency_text}\n"
        f"Следующее: {next_date_str}"
    )


def format_no_reminder_set(username: str) -> str:
    """Format message when no reminder is set."""
    return f"✅ Контакт *@{username}* сохранен без напоминания."


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
    """Format contact card text with markdown escaping."""
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

    # Escape markdown in user-provided text
    safe_desc = escape_markdown(desc_text, version=1) if desc_text else ""
    safe_tags = escape_markdown(tags_text, version=1) if tags_text else ""

    # Build card: name/username, description, tags, status
    if display_name:
        safe_name = escape_markdown(display_name, version=1)
        text = f"{prefix}*{safe_name}* (@{username})\n"
    else:
        text = f"{prefix}*@{username}*\n"
    if safe_desc:
        text += f"{safe_desc}\n"
    if safe_tags:
        text += f"{safe_tags}\n"
    text += status_text

    return text


def format_existing_contact_found(username: str) -> str:
    """Format message when user re-forwards an existing contact."""
    return f"📇 *@{username}* уже в твоих контактах.\n\nЧто хочешь сделать?"


def format_custom_interval_prompt() -> str:
    """Format prompt for custom interval input."""
    return (
        "Введи интервал в днях (число от 1 до 365):\n\n"
        "Например: `45` — напоминание раз в 45 дней"
    )


def format_custom_date_prompt() -> str:
    """Format prompt for custom date input."""
    return (
        "Когда напомнить? Напиши дату в любом формате:\n\n"
        "• `завтра`\n"
        "• `через неделю`\n"
        "• `в пятницу`\n"
        "• `15 февраля`\n"
        "• `25.02.2025`"
    )


def format_description_prompt(username: str, display_name: str) -> str:
    """Format prompt for contact description."""
    safe_display_name = escape_markdown(display_name, version=1)
    return (
        f"📇 *{safe_display_name}* (@{username})\n\n"
        f"Напиши описание:\n"
        f"`коллега из IT`\n\n"
        f"Или /cancel для отмены."
    )


def format_edit_description_prompt(username: str) -> str:
    """Format prompt for editing contact description."""
    return (
        f"✏️ Редактирование *@{username}*\n\n"
        f"Отправь новое описание контакта:"
    )
