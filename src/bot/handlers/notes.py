"""
Handlers for browsing saved conversation notes.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytz
from telegram import Update
from telegram.ext import ContextTypes

from src.bot.keyboards import get_notes_browser_keyboard, get_main_reply_keyboard
from src.bot.messages import format_notes_empty, format_notes_page
from src.config import settings
from src.db.engine import get_supabase
from src.db.repositories.contacts import ContactRepository
from src.services.contact_notes_service import ContactNoteEntry, list_contact_notes

DEFAULT_NOTES_RANGE = "all"
DEFAULT_NOTES_ORDER = "new"
NOTES_PAGE_SIZE = 8
_ALLOWED_RANGES = {"all", "today", "week", "month"}
_ALLOWED_ORDERS = {"new", "old"}


def _normalize_notes_range(value: str | None) -> str:
    """Normalize note range filter values coming from callbacks."""
    return value if value in _ALLOWED_RANGES else DEFAULT_NOTES_RANGE


def _normalize_notes_order(value: str | None) -> str:
    """Normalize note ordering values coming from callbacks."""
    return value if value in _ALLOWED_ORDERS else DEFAULT_NOTES_ORDER


def _apply_date_filter(
    notes: list[ContactNoteEntry],
    date_range: str,
    now: datetime,
) -> list[ContactNoteEntry]:
    """Filter notes by date range using the project timezone."""
    safe_range = _normalize_notes_range(date_range)
    now_date = now.date()

    filtered: list[ContactNoteEntry] = []
    for note in notes:
        note_dt = note.created_at.astimezone(now.tzinfo) if note.created_at.tzinfo else note.created_at
        note_date = note_dt.date()

        if safe_range == "today" and note_date != now_date:
            continue
        if safe_range == "week" and note_dt < now - timedelta(days=7):
            continue
        if safe_range == "month" and note_dt < now - timedelta(days=30):
            continue

        filtered.append(note)

    return filtered


async def build_notes_view(
    user_id: int,
    date_range: str = DEFAULT_NOTES_RANGE,
    order: str = DEFAULT_NOTES_ORDER,
    page: int = 0,
) -> tuple[str, object | None]:
    """Build the notes screen text and inline keyboard for one user."""
    safe_range = _normalize_notes_range(date_range)
    safe_order = _normalize_notes_order(order)

    client = await get_supabase()
    contact_repo = ContactRepository(client)
    contacts = await contact_repo.get_all_for_user(user_id)
    contacts_by_id = {str(contact.id): contact for contact in contacts}

    if not contacts_by_id:
        return (
            "📝 <b>Заметки пока недоступны</b>\n\n"
            "Сначала сохрани хотя бы один контакт, а затем можно будет фиксировать итоги общения.",
            None,
        )

    notes = await list_contact_notes(set(contacts_by_id))
    if not notes:
        return (
            format_notes_empty(has_saved_notes=False),
            None,
        )

    tz = pytz.timezone(settings.TIMEZONE)
    now = datetime.now(tz)
    filtered_notes = _apply_date_filter(notes, safe_range, now)
    filtered_notes.sort(
        key=lambda note: note.created_at,
        reverse=safe_order == "new",
    )

    total_filtered = len(filtered_notes)
    total_pages = max(1, (total_filtered + NOTES_PAGE_SIZE - 1) // NOTES_PAGE_SIZE)
    safe_page = max(0, min(page, total_pages - 1))

    if not filtered_notes:
        return (
            format_notes_empty(has_saved_notes=True, date_range=safe_range),
            get_notes_browser_keyboard(safe_range, safe_order, 0, 1),
        )

    start_index = safe_page * NOTES_PAGE_SIZE
    page_notes = filtered_notes[start_index : start_index + NOTES_PAGE_SIZE]
    text = format_notes_page(
        notes=page_notes,
        contacts_by_id=contacts_by_id,
        date_range=safe_range,
        order=safe_order,
        page=safe_page,
        total_pages=total_pages,
        total_notes=total_filtered,
        start_index=start_index,
        timezone_name=settings.TIMEZONE,
    )
    keyboard = get_notes_browser_keyboard(safe_range, safe_order, safe_page, total_pages)
    return text, keyboard


async def handle_notes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the dedicated notes section from the reply keyboard."""
    text, keyboard = await build_notes_view(update.effective_user.id)
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard or get_main_reply_keyboard(update.effective_user.id),
    )


async def handle_notes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline filters and pagination inside the notes section."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    date_range = parts[1] if len(parts) > 1 else DEFAULT_NOTES_RANGE
    order = parts[2] if len(parts) > 2 else DEFAULT_NOTES_ORDER

    try:
        page = int(parts[3]) if len(parts) > 3 else 0
    except ValueError:
        page = 0

    text, keyboard = await build_notes_view(
        update.effective_user.id,
        date_range=date_range,
        order=order,
        page=page,
    )
    await query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
