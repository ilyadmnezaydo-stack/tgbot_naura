"""
Telegram Application setup and message routing.
"""
import logging
import re
from datetime import date, timedelta
from html import escape as html_escape
from uuid import UUID, uuid4

from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from src.bot.input_text import (
    clear_input_text_override,
    get_input_text,
    set_input_text_override,
)
from src.bot.handlers.callbacks import (
    get_callback_handler,
    handle_contact_note_input,
    send_contact_card,
)
from src.bot.handlers.analytics import get_owner_handlers, owner_dashboard_command
from src.bot.handlers.contacts import (
    add_command,
    get_contact_handlers,
    handle_add_from_prompt,
    handle_edit_from_prompt,
    handle_contact_lookup_from_list,
    handle_list_contacts,
    search_command,
)
from src.bot.handlers.notes import handle_notes_command
from src.bot.handlers.payments import (
    donate_command,
    get_payment_handlers,
    handle_cloudpayments_amount_input,
    handle_donation_amount_input,
)
from src.bot.handlers.forwarded import (
    get_forwarded_handler,
    handle_pending_contact_description,
)
from src.bot.handlers.search import looks_like_search_query, perform_search
from src.bot.handlers.start import get_start_handlers, help_command
from src.bot.handlers.support import (
    handle_support_admin_reply_input,
    handle_support_followup_input,
    handle_support_question_input,
)
from src.bot.keyboards import (
    BUTTON_ADD_CONTACT,
    BUTTON_CANCEL_ACTION,
    BUTTON_HELP,
    BUTTON_LIST_CONTACTS,
    BUTTON_NOTES,
    BUTTON_OWNER_DASHBOARD,
    BUTTON_SEARCH_CONTACTS,
    BUTTON_SUPPORT,
    get_confirm_add_username_keyboard,
    get_main_reply_keyboard,
    get_voice_subscription_offer_keyboard,
)
from src.bot.messages import (
    format_reminder_set,
    format_username_not_found,
)
from src.bot.parsers.frequency import format_frequency, parse_date
from src.config import settings
from src.db.engine import get_supabase
from src.db.repositories.contacts import ContactRepository
from src.scheduler.setup import setup_scheduler
from src.services.analytics_service import record_button_click, record_interaction
from src.services.speech_to_text_service import (
    EmptyTranscription,
    SpeechFileTooLarge,
    SpeechToTextService,
    SpeechToTextUnavailable,
)
from src.services.telegram_username_service import (
    UsernameValidationUnavailable,
    validate_public_username,
)
from src.services.voice_access_service import (
    VOICE_SUBSCRIPTION_PRICE_RUB,
    ensure_voice_input_access,
)
from src.bot.voice_messages import (
    format_voice_subscription_offer,
    format_voice_trial_started,
)

USERNAME_REGEX = re.compile(r"@([a-zA-Z][a-zA-Z0-9_]{4,31})")

logger = logging.getLogger(__name__)

FLOW_STATE_KEYS = {
    "pending_contact",
    "draft_contact",
    "offered_contacts",
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
    "awaiting_support_question",
    "awaiting_support_admin_reply",
    "awaiting_support_followup",
    "contact_list_page",
    "setting_reminder_for",
    "search_query",
}


def extract_username(text: str) -> str | None:
    """Extract the first Telegram username from text."""
    match = USERNAME_REGEX.search(text)
    return match.group(1) if match else None


def extract_context_without_username(text: str, username: str) -> str:
    """Remove one @username mention and keep only the surrounding context text."""
    context_text = re.sub(
        rf"@{re.escape(username)}\b",
        " ",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    return " ".join(context_text.strip(" \t\r\n,;:()[]{}-–—").split())


def store_offered_contact(context, username: str, raw_description: str) -> str:
    """Save one pending @username offer and return its short callback token."""
    offer_id = uuid4().hex[:8]
    offers = context.user_data.setdefault("offered_contacts", {})
    offers[offer_id] = {
        "username": username,
        "raw_description": raw_description,
    }
    if len(offers) > 20:
        oldest_key = next(iter(offers))
        offers.pop(oldest_key, None)
    return offer_id


def clear_flow_state(context) -> None:
    """Clear any active multi-step flow from user_data."""
    for key in FLOW_STATE_KEYS:
        context.user_data.pop(key, None)


async def check_and_offer_username_contact(update: Update, context, text: str) -> bool:
    """
    Check if a message contains @username and offer to add it as a contact.
    Returns True if the username flow handled the message.
    """
    username = extract_username(text)
    if not username:
        return False
    username = username.lower()

    user_id = update.effective_user.id
    client = await get_supabase()
    repo = ContactRepository(client)
    existing = await repo.get_by_username(user_id, username)
    validation_available = True
    try:
        validation = await validate_public_username(username)
    except UsernameValidationUnavailable:
        validation_available = False
        validation = None

    if validation_available and validation and not validation.exists and not existing:
        await update.message.reply_text(
            format_username_not_found(username),
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    if existing:
        await update.message.reply_text(
            f"Контакт <b>@{username}</b> уже есть в списке.\n"
            "Открой «👥 Контакты», если хочешь обновить карточку.",
            parse_mode="HTML",
        )
        return True

    offer_id = store_offered_contact(
        context,
        username=username,
        raw_description=extract_context_without_username(text, username),
    )
    await update.message.reply_text(
        f"Похоже, ты упомянул <b>@{username}</b>.\n\nДобавить его в контакты?",
        parse_mode="HTML",
        reply_markup=get_confirm_add_username_keyboard(offer_id, username),
    )
    return True


async def handle_navigation_button(update: Update, context, text: str) -> bool:
    """Handle taps on the persistent bottom keyboard."""
    user_id = update.effective_user.id

    if text == BUTTON_CANCEL_ACTION:
        await record_button_click(user_id, "reply:cancel", BUTTON_CANCEL_ACTION)
        await cancel_command(update, context)
        return True

    if text == BUTTON_ADD_CONTACT:
        await record_button_click(user_id, "reply:add_contact", BUTTON_ADD_CONTACT)
        clear_flow_state(context)
        await add_command(update, context)
        return True

    if text == BUTTON_LIST_CONTACTS:
        await record_button_click(user_id, "reply:list_contacts", BUTTON_LIST_CONTACTS)
        clear_flow_state(context)
        await handle_list_contacts(update, context)
        return True

    if text == BUTTON_SEARCH_CONTACTS:
        await record_button_click(user_id, "reply:search_contacts", BUTTON_SEARCH_CONTACTS)
        clear_flow_state(context)
        await search_command(update, context)
        return True

    if text == BUTTON_NOTES:
        await record_button_click(user_id, "reply:notes", BUTTON_NOTES)
        clear_flow_state(context)
        await handle_notes_command(update, context)
        return True

    if text == BUTTON_OWNER_DASHBOARD:
        clear_flow_state(context)
        await owner_dashboard_command(update, context)
        return True

    if text == BUTTON_SUPPORT:
        await record_button_click(user_id, "reply:support", BUTTON_SUPPORT)
        clear_flow_state(context)
        await donate_command(update, context)
        return True

    if text == BUTTON_HELP:
        await record_button_click(user_id, "reply:help", BUTTON_HELP)
        await help_command(update, context)
        return True

    return False


async def route_message(update: Update, context) -> None:
    """
    Main message router.
    Handles keyboard navigation, pending flows, and free-form input.
    """
    text = get_input_text(update, context)
    if not text:
        return

    await route_text_input(update, context, text)


async def route_text_input(
    update: Update,
    context,
    text: str,
    *,
    allow_navigation_buttons: bool = True,
) -> None:
    """Route normalized text through the regular bot flows."""
    if allow_navigation_buttons and await handle_navigation_button(update, context, text.strip()):
        return

    await record_interaction(update.effective_user.id)

    if await handle_cloudpayments_amount_input(update, context):
        return

    if await handle_donation_amount_input(update, context):
        return

    if await handle_pending_contact_description(update, context):
        return

    if await handle_contact_note_input(update, context):
        return

    if await handle_support_admin_reply_input(update, context):
        return

    if await handle_support_question_input(update, context):
        return

    if await handle_support_followup_input(update, context):
        return

    if context.user_data.get("awaiting_custom_interval"):
        await handle_custom_interval_input(update, context)
        return

    if context.user_data.get("awaiting_custom_date"):
        await handle_custom_date_input(update, context)
        return

    if context.user_data.get("editing_contact"):
        await handle_edit_from_prompt(update, context)
        return

    if context.user_data.get("awaiting_add"):
        await handle_add_from_prompt(update, context)
        return

    if context.user_data.get("awaiting_search"):
        context.user_data.pop("awaiting_search", None)
        await perform_search(update, context, text)
        return

    if await handle_contact_lookup_from_list(update, context):
        return

    if await check_and_offer_username_contact(update, context, text):
        return

    if context.user_data.get("_input_text_override") is not None and looks_like_search_query(text):
        await perform_search(update, context, text)
        return

    await update.message.reply_text(
        "Не понял, какой сценарий ты хочешь запустить.\n\n"
        "Можно:\n"
        "• выбрать действие на клавиатуре ниже\n"
        "• переслать сообщение человека\n"
        "• или сразу отправить <code>@username</code> / <code>@username короткий контекст</code>",
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard(update.effective_user.id),
    )


async def route_voice_message(update: Update, context) -> None:
    """Transcribe a voice or audio message and reuse the regular text router."""
    if not update.message:
        return

    access = await ensure_voice_input_access(update.effective_user)
    if not access.has_access:
        await update.message.reply_text(
            format_voice_subscription_offer(
                trial_expires_at=access.trial_expires_at,
                price_rub=VOICE_SUBSCRIPTION_PRICE_RUB,
            ),
            parse_mode="HTML",
            reply_markup=get_voice_subscription_offer_keyboard(),
        )
        return

    if access.access_type == "trial_started":
        await update.message.reply_text(
            format_voice_trial_started(access.trial_expires_at),
            parse_mode="HTML",
        )

    stt_service = SpeechToTextService()

    try:
        transcription = await stt_service.transcribe_message(context.bot, update.message)
    except SpeechFileTooLarge as exc:
        await update.message.reply_text(
            f"Голосовое получилось слишком большим для расшифровки. Сейчас лимит около {exc.max_file_mb} МБ.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return
    except EmptyTranscription:
        await update.message.reply_text(
            "Не смог разобрать речь в этом сообщении. Попробуй прислать текстом или записать голосовое чуть яснее.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return
    except SpeechToTextUnavailable:
        await update.message.reply_text(
            "Сервис расшифровки сейчас недоступен. Можно прислать сообщение текстом или позже поднять `TRANSCRIPTION_*` endpoint.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return
    except Exception:
        logger.exception("Failed to transcribe audio message")
        await update.message.reply_text(
            "Не получилось обработать голосовое сообщение. Попробуй ещё раз или пришли текстом.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return

    if transcription.text.strip().lower() in {"отмена", "cancel"}:
        await cancel_command(update, context)
        return

    logger.info("Voice transcription (%s): %s", transcription.source, transcription.text)

    if context.user_data.get("awaiting_search"):
        await update.message.reply_text(
            f"Распознал запрос: <code>{html_escape(transcription.text)}</code>\nИщу по тегам, потом по контексту.",
            parse_mode="HTML",
        )
    elif context.user_data.get("awaiting_contact_note"):
        await update.message.reply_text(
            f"Распознал заметку: <code>{html_escape(transcription.text)}</code>\nСохраняю её к контакту.",
            parse_mode="HTML",
        )

    set_input_text_override(context, transcription.text)
    try:
        await route_text_input(
            update,
            context,
            transcription.text,
            allow_navigation_buttons=False,
        )
    finally:
        clear_input_text_override(context)


async def handle_custom_interval_input(update: Update, context) -> None:
    """Handle custom interval input in days."""
    text = get_input_text(update, context, strip=True) or ""
    contact_id = context.user_data.get("awaiting_custom_interval")
    del context.user_data["awaiting_custom_interval"]

    try:
        days = int(text)
        if days < 1 or days > 365:
            raise ValueError("Out of range")
    except ValueError:
        await update.message.reply_text(
            "Нужен целый интервал от 1 до 365 дней.\n"
            "Например: <code>45</code>",
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        context.user_data["awaiting_custom_interval"] = contact_id
        return

    next_date = date.today() + timedelta(days=days)

    client = await get_supabase()
    repo = ContactRepository(client)
    contact = await repo.get_by_id(UUID(contact_id))

    if contact:
        await repo.update(
            contact.id,
            reminder_frequency="custom",
            custom_interval_days=days,
            next_reminder_date=next_date,
            status="active",
        )
        if context.user_data.get("editing_contact") == contact_id:
            context.user_data.pop("editing_contact", None)
            context.user_data.pop("editing_field", None)

        freq_text = format_frequency("custom", days)
        await update.message.reply_text(
            format_reminder_set(contact.username, freq_text, next_date.strftime("%d.%m.%Y")),
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        await send_contact_card(update.message, await repo.get_by_id(UUID(contact_id)))


async def handle_custom_date_input(update: Update, context) -> None:
    """Handle custom date input for one-time reminders."""
    from src.services.ai_service import AIService

    text = get_input_text(update, context, strip=True) or ""
    contact_id = context.user_data.get("awaiting_custom_date")
    del context.user_data["awaiting_custom_date"]

    reminder_date = parse_date(text)
    if not reminder_date:
        ai_service = AIService()
        reminder_date = await ai_service.parse_date(text)

    if not reminder_date:
        await update.message.reply_text(
            "Не удалось распознать дату.\n\n"
            "Попробуй написать, например:\n"
            "• <code>завтра</code>\n"
            "• <code>через неделю</code>\n"
            "• <code>15 апреля</code>\n"
            "• <code>в пятницу</code>\n"
            "• <code>25.04.2026</code>",
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        context.user_data["awaiting_custom_date"] = contact_id
        return

    if reminder_date <= date.today():
        await update.message.reply_text(
            "Нужна дата в будущем.\n"
            "Попробуй прислать другую:",
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        context.user_data["awaiting_custom_date"] = contact_id
        return

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
        if context.user_data.get("editing_contact") == contact_id:
            context.user_data.pop("editing_contact", None)
            context.user_data.pop("editing_field", None)

        await update.message.reply_text(
            format_reminder_set(contact.username, "однократно", reminder_date.strftime("%d.%m.%Y")),
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        await send_contact_card(update.message, await repo.get_by_id(UUID(contact_id)))


async def cancel_command(update: Update, context) -> None:
    """Cancel any active multi-step operation."""
    cancelled = any(key in context.user_data for key in FLOW_STATE_KEYS)
    clear_flow_state(context)

    if cancelled:
        await update.message.reply_text(
            "Текущий шаг отменён. Можно сразу выбрать новый сценарий на клавиатуре.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
    else:
        await update.message.reply_text(
            "Сейчас активного шага нет. Клавиатура уже готова к работе.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and notify the user with a friendly fallback message."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message:
        text = (
            "Произошла техническая ошибка на стороне бота.\n"
            "Попробуй повторить действие чуть позже."
        )
        try:
            await update.effective_message.reply_text(
                text,
                reply_markup=get_main_reply_keyboard(update.effective_user.id if update.effective_user else None),
            )
        except Exception as exc:
            logger.error(f"Failed to send error message to user: {exc}")


def create_application() -> Application:
    """Create and configure the Telegram bot application."""
    logger.info("Creating Telegram application...")

    # Rely on the system environment defaults for TLS/network configuration.
    telegram_request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=20.0,
        write_timeout=20.0,
        pool_timeout=5.0,
        media_write_timeout=60.0,
    )
    get_updates_request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=45.0,
        write_timeout=20.0,
        pool_timeout=5.0,
    )

    application = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .request(telegram_request)
        .get_updates_request(get_updates_request)
        .build()
    )

    for handler in get_start_handlers():
        application.add_handler(handler)
    for handler in get_owner_handlers():
        application.add_handler(handler)
    for handler in get_payment_handlers():
        application.add_handler(handler)

    for handler in get_contact_handlers():
        application.add_handler(handler)
    application.add_handler(get_callback_handler())
    application.add_handler(get_forwarded_handler())
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            route_message,
        )
    )
    application.add_handler(
        MessageHandler(
            (filters.VOICE | filters.AUDIO) & ~filters.COMMAND,
            route_voice_message,
        )
    )
    application.add_error_handler(error_handler)

    setup_scheduler(application)

    logger.info("Application configured successfully")
    return application
