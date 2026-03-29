"""
Support flow: AI first line, then human escalation to the owner.
"""
from __future__ import annotations

from datetime import datetime

import pytz
from telegram import Update
from telegram.ext import ContextTypes

from src.bot.input_text import get_input_text
from src.bot.keyboards import (
    get_help_inline_keyboard,
    get_main_reply_keyboard,
    get_support_admin_keyboard,
    get_support_feedback_keyboard,
    is_owner_user,
)
from src.bot.messages import (
    format_support_admin_reply_prompt,
    format_support_admin_skip,
    format_support_admin_ticket,
    format_support_ai_answer,
    format_support_escalated,
    format_support_feedback_thanks,
    format_support_followup_prompt,
    format_support_no_admins,
    format_support_prompt,
    format_support_user_answer,
)
from src.config import settings
from src.services.ai_service import AIService
from src.services.support_service import (
    create_support_ticket,
    get_support_ticket,
    support_ticket_to_namespace,
    update_support_ticket,
)


SUPPORT_CONTEXT_KEYS = {
    "awaiting_support_question",
    "awaiting_support_admin_reply",
    "awaiting_support_followup",
}

_INTERRUPTED_FLOW_KEYS = {
    "pending_contact",
    "draft_contact",
    "awaiting_add",
    "awaiting_search",
    "editing_contact",
    "editing_field",
    "awaiting_custom_interval",
    "awaiting_custom_date",
    "awaiting_contact_note",
    "awaiting_contact_lookup",
    "awaiting_donation_amount",
    "awaiting_sbp_amount",
    "contact_list_page",
    "setting_reminder_for",
    "search_query",
}


def _now() -> datetime:
    """Return timezone-aware current time in the project timezone."""
    return datetime.now(pytz.timezone(settings.TIMEZONE))


def _admin_user_ids() -> list[int]:
    """Return configured admin IDs for support escalation."""
    return settings.all_admin_user_ids


def _clear_support_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear support-specific user state."""
    for key in SUPPORT_CONTEXT_KEYS:
        context.user_data.pop(key, None)


def _clear_interrupted_flows(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear other flows before entering support."""
    for key in _INTERRUPTED_FLOW_KEYS:
        context.user_data.pop(key, None)


async def _notify_admins_about_ticket(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    ticket,
) -> None:
    """Send one support ticket to all configured admins."""
    if not _admin_user_ids():
        return

    text = format_support_admin_ticket(support_ticket_to_namespace(ticket))
    keyboard = get_support_admin_keyboard(ticket.id)

    for admin_id in _admin_user_ids():
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except Exception:
            # Failing one admin notification should not break user flow.
            continue


async def handle_support_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start support intake from the inline help button."""
    query = update.callback_query
    await query.answer()

    _clear_interrupted_flows(context)
    _clear_support_state(context)
    context.user_data["awaiting_support_question"] = True

    await query.message.reply_text(
        format_support_prompt(),
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard(update.effective_user.id),
    )


async def handle_support_question_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Handle the first user message after opening support."""
    if not context.user_data.get("awaiting_support_question"):
        return False

    question = get_input_text(update, context, strip=True) or ""
    if not question:
        return True

    _clear_support_state(context)
    now = _now()
    ai_service = AIService()
    triage = await ai_service.triage_support_question(question)

    is_complex = not triage or triage.is_complex or not triage.answer
    if not is_complex:
        await create_support_ticket(
            user_id=update.effective_user.id,
            user_username=update.effective_user.username,
            user_first_name=update.effective_user.first_name,
            question=question,
            source="initial",
            status="ai_answered",
            ai_answer=triage.answer,
            created_at=now,
        )
        await update.message.reply_text(
            format_support_ai_answer(triage.answer),
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    ticket = await create_support_ticket(
        user_id=update.effective_user.id,
        user_username=update.effective_user.username,
        user_first_name=update.effective_user.first_name,
        question=question,
        source="initial",
        status="pending_admin",
        created_at=now,
    )

    if not _admin_user_ids():
        await update.message.reply_text(
            format_support_no_admins(),
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    await _notify_admins_about_ticket(update, context, ticket)
    await update.message.reply_text(
        format_support_escalated(),
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard(update.effective_user.id),
    )
    return True


async def handle_support_followup_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Handle one follow-up question after the admin answer."""
    parent_ticket_id = context.user_data.get("awaiting_support_followup")
    if not parent_ticket_id:
        return False

    question = get_input_text(update, context, strip=True) or ""
    if not question:
        return True

    _clear_support_state(context)
    now = _now()
    ticket = await create_support_ticket(
        user_id=update.effective_user.id,
        user_username=update.effective_user.username,
        user_first_name=update.effective_user.first_name,
        question=question,
        source="followup",
        status="pending_admin",
        parent_ticket_id=parent_ticket_id,
        created_at=now,
    )

    if not _admin_user_ids():
        await update.message.reply_text(
            format_support_no_admins(),
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    await _notify_admins_about_ticket(update, context, ticket)
    await update.message.reply_text(
        format_support_escalated(),
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard(update.effective_user.id),
    )
    return True


async def handle_support_admin_reply_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Handle the admin message that should be delivered to the user."""
    ticket_id = context.user_data.get("awaiting_support_admin_reply")
    if not ticket_id or not is_owner_user(update.effective_user.id):
        return False

    answer = get_input_text(update, context, strip=True) or ""
    if not answer:
        return True

    ticket = await get_support_ticket(ticket_id)
    _clear_support_state(context)
    if not ticket:
        await update.message.reply_text(
            "Не нашёл этот тикет. Попробуй открыть следующий вопрос заново.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    now = _now()
    await update_support_ticket(
        ticket_id,
        status="answered",
        admin_id=update.effective_user.id,
        admin_reply=answer,
        answered_at=now,
        updated_at=now,
    )

    try:
        await context.bot.send_message(
            chat_id=ticket.user_id,
            text=format_support_user_answer(answer),
            parse_mode="HTML",
            reply_markup=get_support_feedback_keyboard(ticket_id),
        )
        await update.message.reply_text(
            "Ответ отправил пользователю.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
    except Exception:
        await update.message.reply_text(
            "Не смог отправить ответ пользователю. Возможно, чат с ботом недоступен.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )

    return True


async def handle_support_admin_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle admin-side support actions."""
    query = update.callback_query
    await query.answer()

    if not is_owner_user(update.effective_user.id):
        await query.answer("Это действие доступно только админу.", show_alert=True)
        return

    _, action, ticket_id = (query.data or "").split(":", 2)
    ticket = await get_support_ticket(ticket_id)
    if not ticket:
        await query.answer("Тикет не найден.", show_alert=True)
        return

    if action == "reply":
        if ticket.status not in {"pending_admin", "followup_requested"}:
            await query.answer("Этот вопрос уже обрабатывается.", show_alert=True)
            return

        await update_support_ticket(
            ticket_id,
            status="awaiting_admin_reply",
            admin_id=update.effective_user.id,
            updated_at=_now(),
        )
        _clear_support_state(context)
        context.user_data["awaiting_support_admin_reply"] = ticket_id
        await query.message.edit_reply_markup(reply_markup=None)
        await query.message.reply_text(
            format_support_admin_reply_prompt(support_ticket_to_namespace(ticket)),
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return

    if action == "skip":
        if ticket.status not in {"pending_admin", "followup_requested"}:
            await query.answer("Этот вопрос уже обработан.", show_alert=True)
            return

        await update_support_ticket(
            ticket_id,
            status="ignored",
            admin_id=update.effective_user.id,
            updated_at=_now(),
        )
        await query.message.edit_reply_markup(reply_markup=None)
        await query.message.reply_text(
            format_support_admin_skip(),
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )


async def handle_support_feedback_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle user feedback after the admin answer."""
    query = update.callback_query
    await query.answer()

    _, action, ticket_id = (query.data or "").split(":", 2)
    ticket = await get_support_ticket(ticket_id)
    if not ticket or ticket.user_id != update.effective_user.id:
        await query.answer("Этот ответ уже недоступен.", show_alert=True)
        return

    if action == "helped":
        await update_support_ticket(
            ticket_id,
            status="closed",
            feedback="helped",
            updated_at=_now(),
        )
        await query.message.edit_reply_markup(reply_markup=None)
        await query.message.reply_text(
            format_support_feedback_thanks(),
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return

    if action == "followup":
        await update_support_ticket(
            ticket_id,
            status="followup_requested",
            feedback="followup_requested",
            updated_at=_now(),
        )
        _clear_support_state(context)
        context.user_data["awaiting_support_followup"] = ticket_id
        await query.message.edit_reply_markup(reply_markup=None)
        await query.message.reply_text(
            format_support_followup_prompt(),
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )


def get_help_keyboard():
    """Compatibility helper for support button under help text."""
    return get_help_inline_keyboard()
