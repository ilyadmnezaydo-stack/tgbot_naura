"""
Centralized keyboard definitions for the bot.
"""
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from src.config import settings


BUTTON_ADD_CONTACT = "✨ Добавить"
BUTTON_LIST_CONTACTS = "👥 Контакты"
BUTTON_SEARCH_CONTACTS = "🔎 Поиск"
BUTTON_NOTES = "📝 Заметки"
BUTTON_SUPPORT = "⭐ Поддержать"
BUTTON_HELP = "ℹ️ Помощь"
BUTTON_CANCEL_ACTION = "↩️ Отмена"
BUTTON_OWNER_DASHBOARD = "📊 Дашборд"


def is_admin_user(user_id: int | None) -> bool:
    """Return whether the user should see admin-only controls."""
    if user_id is None:
        return False
    return user_id in set(settings.all_admin_user_ids)


def is_owner_user(user_id: int | None) -> bool:
    """Backward-compatible alias for admin access checks."""
    return is_admin_user(user_id)


def get_main_reply_keyboard(user_id: int | None = None) -> ReplyKeyboardMarkup:
    """Create the persistent bottom keyboard used for primary navigation."""
    keyboard = [
        [KeyboardButton(BUTTON_ADD_CONTACT), KeyboardButton(BUTTON_SEARCH_CONTACTS)],
        [KeyboardButton(BUTTON_LIST_CONTACTS), KeyboardButton(BUTTON_NOTES)],
        [KeyboardButton(BUTTON_HELP), KeyboardButton(BUTTON_SUPPORT)],
        [KeyboardButton(BUTTON_CANCEL_ACTION)],
    ]
    if is_admin_user(user_id):
        keyboard.append([KeyboardButton(BUTTON_OWNER_DASHBOARD)])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Напиши: @anna дизайнер из команды",
    )


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Create a compact inline fallback menu."""
    keyboard = [
        [InlineKeyboardButton("✨ Добавить контакт", callback_data="menu:add")],
        [InlineKeyboardButton("👥 Контакты", callback_data="menu:list")],
        [InlineKeyboardButton("🔎 Умный поиск", callback_data="menu:search")],
        [InlineKeyboardButton("📝 Заметки", callback_data="menu:notes")],
        [InlineKeyboardButton("⭐ Поддержать", callback_data="menu:donate")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_help_inline_keyboard() -> InlineKeyboardMarkup:
    """Create inline actions shown under the help text."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("💬 Поддержка", callback_data="support:start")]]
    )


def get_voice_subscription_offer_keyboard() -> InlineKeyboardMarkup:
    """Create an inline CTA for buying voice-input access after trial expiry."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎙 Купить голосовой ввод — 399 ₽/мес", callback_data="voice_sub:buy")],
            [InlineKeyboardButton("Позже", callback_data="voice_sub:later")],
        ]
    )


def get_voice_subscription_mock_payment_keyboard(payment_id: str) -> InlineKeyboardMarkup:
    """Create inline actions for the mocked voice subscription payment."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Активировать подписку", callback_data=f"voice_sub:activate:{payment_id}")],
            [InlineKeyboardButton("Не сейчас", callback_data="voice_sub:later")],
        ]
    )


def get_confirm_contact_keyboard() -> InlineKeyboardMarkup:
    """Create confirmation keyboard after contact preview."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Всё верно", callback_data="confirm_contact"),
            InlineKeyboardButton("✏️ Исправить", callback_data="edit_draft"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_optional_context_keyboard() -> InlineKeyboardMarkup:
    """Create inline actions for choosing whether to add context now."""
    keyboard = [
        [
            InlineKeyboardButton("📝 Добавить контекст", callback_data="pending_context:add"),
            InlineKeyboardButton("Далее", callback_data="pending_context:skip"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_reminder_type_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for selecting reminder type after saving contact."""
    keyboard = [
        [InlineKeyboardButton("🔁 Регулярная частота", callback_data=f"reminder_type:regular:{contact_id}")],
        [InlineKeyboardButton("🗓 Разовое напоминание", callback_data=f"reminder_type:onetime:{contact_id}")],
        [InlineKeyboardButton("🌙 Сохранить без напоминаний", callback_data=f"reminder_type:none:{contact_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_regular_interval_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for selecting a regular reminder interval."""
    keyboard = [
        [InlineKeyboardButton("🗓 Раз в месяц", callback_data=f"interval:monthly:{contact_id}")],
        [InlineKeyboardButton("🗓 Раз в 2 месяца", callback_data=f"interval:bimonthly:{contact_id}")],
        [InlineKeyboardButton("🗓 Раз в квартал", callback_data=f"interval:quarterly:{contact_id}")],
        [InlineKeyboardButton("⚙️ Свой интервал", callback_data=f"interval:custom:{contact_id}")],
        [InlineKeyboardButton("← К выбору типа", callback_data=f"reminder_type:back:{contact_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_onetime_date_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for selecting a one-time reminder date."""
    keyboard = [
        [InlineKeyboardButton("📆 Завтра", callback_data=f"onetime:tomorrow:{contact_id}")],
        [InlineKeyboardButton("📆 Через 7 дней", callback_data=f"onetime:week:{contact_id}")],
        [InlineKeyboardButton("📆 Через 30 дней", callback_data=f"onetime:month:{contact_id}")],
        [InlineKeyboardButton("📝 Своя дата", callback_data=f"onetime:custom:{contact_id}")],
        [InlineKeyboardButton("← К выбору типа", callback_data=f"reminder_type:back:{contact_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_contact_keyboard(contact_id: str, status: str) -> InlineKeyboardMarkup:
    """Create inline actions for a contact card."""
    if status == "paused":
        keyboard = [
            [
                InlineKeyboardButton("✏️ Изменить", callback_data=f"edit:{contact_id}"),
            ],
            [
                InlineKeyboardButton("▶️ Возобновить", callback_data=f"resume:{contact_id}"),
                InlineKeyboardButton("🗑 Удалить", callback_data=f"delete:{contact_id}"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("✏️ Изменить", callback_data=f"edit:{contact_id}"),
            ],
            [
                InlineKeyboardButton("📝 Добавить заметку", callback_data=f"contacted:{contact_id}"),
            ],
            [
                InlineKeyboardButton("⏸ Пауза", callback_data=f"pause:{contact_id}"),
                InlineKeyboardButton("🗑 Удалить", callback_data=f"delete:{contact_id}"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


def get_contact_edit_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    """Create inline actions for choosing what to edit in a contact."""
    keyboard = [
        [
            InlineKeyboardButton("📝 Контекст", callback_data=f"edit_field:description:{contact_id}"),
            InlineKeyboardButton("🏷 Теги", callback_data=f"edit_field:tags:{contact_id}"),
        ],
        [
            InlineKeyboardButton("🔔 Напоминания", callback_data=f"edit_field:reminder:{contact_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def _truncate_button_label(text: str, limit: int = 42) -> str:
    """Keep long inline button labels compact."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _has_distinct_display_name(contact) -> bool:
    """Return True when the saved name adds value beyond the username."""
    display_name = getattr(contact, "display_name", None)
    username = getattr(contact, "username", "") or ""
    if not display_name:
        return False
    return display_name.strip().lower() != username.strip().lower()


def _format_contact_button_label(contact) -> str:
    """Build a compact label for one contact button."""
    if _has_distinct_display_name(contact):
        label = f"{contact.display_name} (@{contact.username})"
    else:
        label = f"@{contact.username}"

    if getattr(contact, "status", "") == "paused":
        label = f"⏸ {label}"
    elif getattr(contact, "status", "") == "one_time":
        label = f"📅 {label}"

    return _truncate_button_label(label)


def get_contacts_browser_keyboard(
    contacts: list,
    page: int,
    page_size: int,
) -> InlineKeyboardMarkup | None:
    """Create contact buttons plus a bottom pagination row."""
    if not contacts:
        return None

    total_pages = max(1, (len(contacts) + page_size - 1) // page_size)
    safe_page = max(0, min(page, total_pages - 1))
    start_index = safe_page * page_size
    page_contacts = contacts[start_index : start_index + page_size]

    keyboard = [
        [
            InlineKeyboardButton(
                _format_contact_button_label(contact),
                callback_data=f"contact_open:{contact.id}",
            )
        ]
        for contact in page_contacts
    ]

    buttons = []
    if safe_page > 0:
        buttons.append(
            InlineKeyboardButton("← Назад", callback_data=f"contacts_page:{safe_page - 1}")
        )
    if safe_page < total_pages - 1:
        buttons.append(
            InlineKeyboardButton("След →", callback_data=f"contacts_page:{safe_page + 1}")
        )
    if buttons:
        keyboard.append(buttons)

    return InlineKeyboardMarkup(keyboard)


def get_contacts_pagination_keyboard(
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup | None:
    """Create inline pagination for the contacts digest."""
    if total_pages <= 1:
        return None

    buttons = []
    if page > 0:
        buttons.append(
            InlineKeyboardButton("← Назад", callback_data=f"contacts_page:{page - 1}")
        )
    if page < total_pages - 1:
        buttons.append(
            InlineKeyboardButton("След →", callback_data=f"contacts_page:{page + 1}")
        )

    return InlineKeyboardMarkup([buttons]) if buttons else None


def get_delete_confirm_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    """Create confirmation keyboard for contact deletion."""
    keyboard = [
        [
            InlineKeyboardButton("🗑 Да, удалить", callback_data=f"delete_yes:{contact_id}"),
            InlineKeyboardButton("↩️ Оставить", callback_data=f"delete_no:{contact_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_confirm_add_username_keyboard(offer_id: str, username: str) -> InlineKeyboardMarkup:
    """Create confirmation keyboard for adding a contact from an @username mention."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Добавить", callback_data=f"add_username_yes:{offer_id}:{username}"),
            InlineKeyboardButton("↩️ Позже", callback_data=f"add_username_no:{offer_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_existing_contact_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for when the user re-forwards an existing contact."""
    keyboard = [
        [InlineKeyboardButton("✏️ Обновить контекст", callback_data=f"update_desc:{contact_id}")],
        [InlineKeyboardButton("🔔 Частота напоминаний", callback_data=f"update_reminder:{contact_id}")],
        [InlineKeyboardButton("🗑 Удалить контакт", callback_data=f"delete:{contact_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_skip_contact_note_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for skipping the post-contact note step."""
    keyboard = [
        [InlineKeyboardButton("Пропустить", callback_data=f"skip_note:{contact_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_support_admin_keyboard(ticket_id: str) -> InlineKeyboardMarkup:
    """Create admin actions for a support ticket."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✍️ Ответить", callback_data=f"support_admin:reply:{ticket_id}"),
                InlineKeyboardButton("🙈 Не отвечать", callback_data=f"support_admin:skip:{ticket_id}"),
            ]
        ]
    )


def get_support_feedback_keyboard(ticket_id: str) -> InlineKeyboardMarkup:
    """Create user feedback buttons after the admin answer."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Помогло, спасибо", callback_data=f"support_feedback:helped:{ticket_id}")],
            [InlineKeyboardButton("✉️ Еще вопрос", callback_data=f"support_feedback:followup:{ticket_id}")],
        ]
    )


def get_notes_browser_keyboard(
    date_range: str,
    order: str,
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Create inline filters and pagination for the dedicated notes section."""
    filter_row = [
        InlineKeyboardButton(
            "• Все" if date_range == "all" else "Все",
            callback_data=f"notes:all:{order}:0",
        ),
        InlineKeyboardButton(
            "• Сегодня" if date_range == "today" else "Сегодня",
            callback_data=f"notes:today:{order}:0",
        ),
    ]
    period_row = [
        InlineKeyboardButton(
            "• 7 дней" if date_range == "week" else "7 дней",
            callback_data=f"notes:week:{order}:0",
        ),
        InlineKeyboardButton(
            "• 30 дней" if date_range == "month" else "30 дней",
            callback_data=f"notes:month:{order}:0",
        ),
    ]
    order_row = [
        InlineKeyboardButton(
            "• Новые сверху" if order == "new" else "Новые сверху",
            callback_data=f"notes:{date_range}:new:0",
        ),
        InlineKeyboardButton(
            "• Старые сверху" if order == "old" else "Старые сверху",
            callback_data=f"notes:{date_range}:old:0",
        ),
    ]

    keyboard = [filter_row, period_row, order_row]

    if total_pages > 1:
        page_buttons = []
        if page > 0:
            page_buttons.append(
                InlineKeyboardButton("← Назад", callback_data=f"notes:{date_range}:{order}:{page - 1}")
            )
        if page < total_pages - 1:
            page_buttons.append(
                InlineKeyboardButton("Дальше →", callback_data=f"notes:{date_range}:{order}:{page + 1}")
            )
        if page_buttons:
            keyboard.append(page_buttons)

    return InlineKeyboardMarkup(keyboard)


def get_owner_dashboard_keyboard(
    section: str = "overview",
    period: str = "week",
) -> InlineKeyboardMarkup:
    """Create section and period navigation for the owner dashboard."""
    section_labels = {
        "overview": "Сводка",
        "users": "Пользователи",
        "contacts": "Контакты",
        "buttons": "Кнопки",
        "notes": "Заметки",
        "support": "Поддержка",
        "donations": "Донаты",
    }
    period_labels = {
        "day": "День",
        "week": "Неделя",
        "month": "Месяц",
        "all": "Всё время",
    }

    def _section_button(key: str) -> InlineKeyboardButton:
        label = section_labels.get(key, key)
        if key == section:
            label = f"• {label}"
        return InlineKeyboardButton(label, callback_data=f"owner_dashboard:{key}:{period}")

    def _period_button(key: str) -> InlineKeyboardButton:
        label = period_labels.get(key, key)
        if key == period:
            label = f"• {label}"
        return InlineKeyboardButton(label, callback_data=f"owner_dashboard:{section}:{key}")

    keyboard = [
        [_section_button("overview"), _section_button("users")],
        [_section_button("contacts"), _section_button("buttons")],
        [_section_button("notes"), _section_button("support")],
        [_section_button("donations")],
        [
            _period_button("day"),
            _period_button("week"),
            _period_button("month"),
            _period_button("all"),
        ],
        [
            InlineKeyboardButton(
                "↻ Обновить",
                callback_data=f"owner_dashboard:refresh:{section}:{period}",
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
