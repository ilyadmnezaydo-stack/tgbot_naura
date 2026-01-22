"""
Centralized keyboard definitions for the bot.
All inline keyboards are defined here for consistency.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ============ MAIN MENU ============

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Create main menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("➕ Добавить контакт", callback_data="menu:add")],
        [InlineKeyboardButton("📋 Мои контакты", callback_data="menu:list")],
        [InlineKeyboardButton("🔍 Найти контакт", callback_data="menu:search")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============ CONTACT CONFIRMATION ============

def get_confirm_contact_keyboard() -> InlineKeyboardMarkup:
    """Create confirmation keyboard after contact preview."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Все верно", callback_data="confirm_contact"),
            InlineKeyboardButton("✏️ Изменить", callback_data="edit_draft"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============ REMINDER TYPE SELECTION ============

def get_reminder_type_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for selecting reminder type after saving contact."""
    keyboard = [
        [InlineKeyboardButton("🔄 Регулярное", callback_data=f"reminder_type:regular:{contact_id}")],
        [InlineKeyboardButton("📆 Разовое", callback_data=f"reminder_type:onetime:{contact_id}")],
        [InlineKeyboardButton("❌ Без напоминаний", callback_data=f"reminder_type:none:{contact_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============ REGULAR REMINDER INTERVALS ============

def get_regular_interval_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for selecting regular reminder interval."""
    keyboard = [
        [InlineKeyboardButton("📅 Раз в месяц", callback_data=f"interval:monthly:{contact_id}")],
        [InlineKeyboardButton("📅 Раз в два месяца", callback_data=f"interval:bimonthly:{contact_id}")],
        [InlineKeyboardButton("📅 Раз в квартал", callback_data=f"interval:quarterly:{contact_id}")],
        [InlineKeyboardButton("⚙️ Свой интервал", callback_data=f"interval:custom:{contact_id}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"reminder_type:back:{contact_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============ ONE-TIME REMINDER DATE ============

def get_onetime_date_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for selecting one-time reminder date."""
    keyboard = [
        [InlineKeyboardButton("📆 Завтра", callback_data=f"onetime:tomorrow:{contact_id}")],
        [InlineKeyboardButton("📆 Через неделю", callback_data=f"onetime:week:{contact_id}")],
        [InlineKeyboardButton("📆 Через месяц", callback_data=f"onetime:month:{contact_id}")],
        [InlineKeyboardButton("📅 Выбрать дату", callback_data=f"onetime:custom:{contact_id}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"reminder_type:back:{contact_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============ CONTACT ACTIONS ============

def get_contact_keyboard(contact_id: str, status: str) -> InlineKeyboardMarkup:
    """Create keyboard for a contact based on its status."""
    if status == "paused":
        keyboard = [
            [
                InlineKeyboardButton("🔔 Поставить напоминание", callback_data=f"resume:{contact_id}"),
                InlineKeyboardButton("✏️ Изменить", callback_data=f"edit:{contact_id}"),
            ],
            [
                InlineKeyboardButton("❌ Удалить", callback_data=f"delete:{contact_id}"),
            ],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("📞 Связался", callback_data=f"contacted:{contact_id}"),
                InlineKeyboardButton("✏️ Изменить", callback_data=f"edit:{contact_id}"),
            ],
            [
                InlineKeyboardButton("⏸️ Приостановить", callback_data=f"pause:{contact_id}"),
                InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete:{contact_id}"),
            ],
        ]
    return InlineKeyboardMarkup(keyboard)


# ============ DELETE CONFIRMATION ============

def get_delete_confirm_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    """Create confirmation keyboard for delete action."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"delete_yes:{contact_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"delete_no:{contact_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============ ADD USERNAME CONFIRMATION ============

def get_confirm_add_username_keyboard(username: str) -> InlineKeyboardMarkup:
    """Create confirmation keyboard for adding a contact from @username mention."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Да", callback_data=f"add_username_yes:{username}"),
            InlineKeyboardButton("❌ Нет", callback_data="add_username_no"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============ EXISTING CONTACT OPTIONS ============

def get_existing_contact_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for when user re-forwards an existing contact."""
    keyboard = [
        [InlineKeyboardButton("✏️ Обновить описание", callback_data=f"update_desc:{contact_id}")],
        [InlineKeyboardButton("🔔 Изменить напоминание", callback_data=f"update_reminder:{contact_id}")],
        [InlineKeyboardButton("🗑️ Удалить контакт", callback_data=f"delete:{contact_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)
