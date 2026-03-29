"""
Payment flows: Telegram Stars and CloudPayments SBP.
"""
from __future__ import annotations

from datetime import datetime
import logging
import re

import pytz
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    Update,
)
from telegram.error import TelegramError
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

from src.bot.input_text import get_input_text
from src.bot.keyboards import (
    BUTTON_CANCEL_ACTION,
    get_main_reply_keyboard,
    get_voice_subscription_mock_payment_keyboard,
)
from src.bot.messages import (
    format_cloudpayments_amount_invalid,
    format_cloudpayments_amount_prompt,
    format_cloudpayments_link_ready,
    format_cloudpayments_unavailable,
    format_donation_amount_invalid,
    format_donation_custom_prompt,
    format_donation_intro,
    format_donation_invoice_sent,
    format_donation_success,
    format_paysupport_text,
)
from src.bot.voice_messages import (
    format_voice_subscription_activated,
    format_voice_subscription_already_active,
    format_voice_subscription_mock_payment,
)
from src.config import settings
from src.services.analytics_service import record_interaction
from src.services.cloudpayments_client import CloudPaymentsClientError
from src.services.payment_service import (
    PaymentConfigurationError,
    PaymentService,
    parse_rub_amount_text,
)
from src.services.payment_support_service import DonationPayment, save_donation_payment
from src.services.voice_access_service import (
    VOICE_SUBSCRIPTION_DAYS,
    VOICE_SUBSCRIPTION_PRICE_RUB,
    activate_voice_input_subscription,
    get_voice_input_access,
)
from src.services.voice_subscription_payment_service import (
    create_mock_voice_subscription_payment,
    get_voice_subscription_payment,
    mark_voice_subscription_payment_paid,
)

logger = logging.getLogger(__name__)

DONATION_AMOUNTS = (50, 100, 250)
DONATION_PAYLOAD_PREFIX = "donation"
CUSTOM_DONATION_CALLBACK = "donate:stars:custom"
LEGACY_CUSTOM_DONATION_CALLBACK = "donate:custom"
SBP_DONATION_CALLBACK = "donate:sbp"
VOICE_SUBSCRIPTION_BUY_CALLBACK = "voice_sub:buy"
VOICE_SUBSCRIPTION_LATER_CALLBACK = "voice_sub:later"
AWAITING_DONATION_AMOUNT_KEY = "awaiting_donation_amount"
AWAITING_SBP_AMOUNT_KEY = "awaiting_sbp_amount"
_CUSTOM_CANCEL_VALUES = {
    "/cancel",
    "cancel",
    "отмена",
    BUTTON_CANCEL_ACTION.lower(),
}


def get_donation_keyboard() -> InlineKeyboardMarkup:
    """Create the mixed support menu: Stars presets plus an SBP branch."""
    rows = [
        [
            InlineKeyboardButton(f"{DONATION_AMOUNTS[0]} ⭐", callback_data=f"donate:stars:{DONATION_AMOUNTS[0]}"),
            InlineKeyboardButton(f"{DONATION_AMOUNTS[1]} ⭐", callback_data=f"donate:stars:{DONATION_AMOUNTS[1]}"),
        ],
        [
            InlineKeyboardButton(f"{DONATION_AMOUNTS[2]} ⭐", callback_data=f"donate:stars:{DONATION_AMOUNTS[2]}"),
            InlineKeyboardButton("✨ Своя сумма Stars", callback_data=CUSTOM_DONATION_CALLBACK),
        ],
        [InlineKeyboardButton("🏦 Оплатить по СБП", callback_data=SBP_DONATION_CALLBACK)],
    ]
    return InlineKeyboardMarkup(rows)


def get_cloudpayments_payment_keyboard(payment_url: str) -> InlineKeyboardMarkup:
    """Create one URL button that opens the CloudPayments SBP payment link."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Открыть оплату по СБП", url=payment_url)]]
    )


async def send_donation_menu(message: Message) -> None:
    """Send the payment menu to the current chat."""
    await message.reply_text(
        format_donation_intro(),
        parse_mode="HTML",
        reply_markup=get_donation_keyboard(),
    )


def _is_donation_payload(payload: str | None) -> bool:
    """Return whether the payment payload belongs to the Stars flow."""
    return bool(payload and payload.startswith(f"{DONATION_PAYLOAD_PREFIX}:"))


def _build_donation_payload(user_id: int, amount: int) -> str:
    """Create a compact invoice payload for a donation amount."""
    return f"{DONATION_PAYLOAD_PREFIX}:{user_id}:{amount}"


def _parse_amount_from_payload(payload: str) -> int:
    """Extract the donated amount from payload."""
    try:
        return int(payload.split(":")[2])
    except (IndexError, ValueError):
        return 0


def _is_private_chat(update: Update) -> bool:
    """Return True if the interaction happens in a private chat."""
    chat = update.effective_chat
    return bool(chat and chat.type == "private")


def _parse_donation_amount_text(text: str | None) -> int | None:
    """Parse a custom Telegram Stars amount from free-form user input."""
    if not text:
        return None

    normalized = text.strip().lower()
    for token in ("stars", "star", "xtr", "звёзды", "звезды", "звезда", "звёзд", "звезд", "⭐"):
        normalized = normalized.replace(token, "")
    normalized = normalized.replace(" ", "").replace("_", "")

    if not re.fullmatch(r"\d+", normalized):
        return None

    amount = int(normalized)
    return amount if amount > 0 else None


def _clear_payment_states(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear any pending payment amount input state."""
    context.user_data.pop(AWAITING_DONATION_AMOUNT_KEY, None)
    context.user_data.pop(AWAITING_SBP_AMOUNT_KEY, None)


async def _send_donation_invoice(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    amount: int,
) -> bool:
    """Create and send a Telegram Stars invoice for the given amount."""
    if not update.effective_chat:
        return False

    try:
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=f"Поддержка проекта • {amount} ⭐",
            description=(
                "Добровольная поддержка развития бота в Telegram Stars. "
                "Спасибо за вклад в проект."
            ),
            payload=_build_donation_payload(update.effective_user.id, amount),
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"Поддержка проекта • {amount} ⭐", amount=amount)],
            start_parameter=f"support-{amount}",
        )
    except TelegramError:
        message = update.effective_message
        if message:
            await message.reply_text(
                "Не смог отправить счёт на эту сумму.\n"
                "Попробуй другое количество Stars.",
                reply_markup=get_main_reply_keyboard(update.effective_user.id),
            )
        return False

    message = update.effective_message
    if message:
        await message.reply_text(
            format_donation_invoice_sent(amount),
            parse_mode="HTML",
        )
    return True


async def _create_cloudpayments_sbp_payment(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    amount_text: str,
) -> bool:
    """Create an SBP payment in CloudPayments and send the payment link."""
    amount = parse_rub_amount_text(amount_text)
    if amount is None:
        await update.message.reply_text(
            format_cloudpayments_amount_invalid(),
            parse_mode="HTML",
        )
        return True

    if not settings.cloudpayments_enabled:
        _clear_payment_states(context)
        await update.message.reply_text(
            format_cloudpayments_unavailable(),
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    try:
        service = PaymentService()
        result = await service.create_sbp_payment(
            telegram_user=update.effective_user,
            amount=amount,
        )
    except PaymentConfigurationError:
        logger.exception("CloudPayments settings are missing")
        await update.message.reply_text(
            format_cloudpayments_unavailable(),
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True
    except CloudPaymentsClientError as exc:
        logger.exception("CloudPayments SBP link creation failed")
        await update.message.reply_text(
            "Не получилось создать ссылку на оплату по СБП.\n"
            f"CloudPayments ответил: {exc}",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True
    except Exception:
        logger.exception("Unexpected CloudPayments SBP creation error")
        await update.message.reply_text(
            "Не получилось подготовить оплату по СБП.\n"
            "Попробуй ещё раз чуть позже.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    _clear_payment_states(context)
    await update.message.reply_text(
        format_cloudpayments_link_ready(result.payment.amount, result.payment.currency),
        parse_mode="HTML",
        reply_markup=get_cloudpayments_payment_keyboard(result.payment_url),
    )
    return True


def _parse_donation_callback(data: str | None) -> tuple[str, int | None]:
    """Support old donate callbacks and new provider-specific ones."""
    value = data or ""
    if value == SBP_DONATION_CALLBACK:
        return "sbp", None
    if value in {CUSTOM_DONATION_CALLBACK, LEGACY_CUSTOM_DONATION_CALLBACK}:
        return "stars_custom", None

    parts = value.split(":")
    if len(parts) >= 3 and parts[1] == "stars":
        try:
            return "stars_amount", int(parts[2])
        except ValueError:
            return "stars_amount", DONATION_AMOUNTS[0]

    try:
        return "stars_amount", int(parts[1])
    except (IndexError, ValueError):
        return "stars_amount", DONATION_AMOUNTS[0]


async def donate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the payment menu or immediately create an invoice from /donate <amount>."""
    await record_interaction(update.effective_user.id)

    if not _is_private_chat(update):
        return

    message = update.effective_message
    if not message:
        return

    amount = _parse_donation_amount_text(" ".join(context.args)) if context.args else None
    if amount is not None:
        _clear_payment_states(context)
        await _send_donation_invoice(update=update, context=context, amount=amount)
        return

    await send_donation_menu(message)


async def paysupport_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Provide a payment support contact flow required by Telegram payments rules."""
    await record_interaction(update.effective_user.id)

    if not _is_private_chat(update):
        return

    if not update.effective_message:
        return

    await update.effective_message.reply_text(
        format_paysupport_text(),
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard(update.effective_user.id),
    )


async def handle_donation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Stars and CloudPayments payment buttons."""
    query = update.callback_query
    await query.answer()

    if not _is_private_chat(update):
        return

    await record_interaction(update.effective_user.id)

    action, amount = _parse_donation_callback(query.data)
    if action == "sbp":
        context.user_data[AWAITING_SBP_AMOUNT_KEY] = True
        context.user_data.pop(AWAITING_DONATION_AMOUNT_KEY, None)
        await query.message.reply_text(
            format_cloudpayments_amount_prompt(),
            parse_mode="HTML",
        )
        return

    if action == "stars_custom":
        context.user_data[AWAITING_DONATION_AMOUNT_KEY] = True
        context.user_data.pop(AWAITING_SBP_AMOUNT_KEY, None)
        await query.message.reply_text(
            format_donation_custom_prompt(),
            parse_mode="HTML",
        )
        return

    _clear_payment_states(context)
    await _send_donation_invoice(update=update, context=context, amount=amount or DONATION_AMOUNTS[0])


async def handle_voice_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the mocked monthly purchase flow for voice-input access."""
    query = update.callback_query
    await query.answer()

    if not _is_private_chat(update):
        return

    await record_interaction(update.effective_user.id)
    data = query.data or ""

    if data == VOICE_SUBSCRIPTION_LATER_CALLBACK:
        await query.message.reply_text(
            "Ок, вернуться к подписке на голосовой ввод можно позже.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return

    if data == VOICE_SUBSCRIPTION_BUY_CALLBACK:
        access = await get_voice_input_access(update.effective_user)
        if access.has_access and access.subscription_expires_at:
            await query.message.reply_text(
                format_voice_subscription_already_active(access.subscription_expires_at),
                parse_mode="HTML",
                reply_markup=get_main_reply_keyboard(update.effective_user.id),
            )
            return

        payment = await create_mock_voice_subscription_payment(
            user_id=update.effective_user.id,
            amount_rub=VOICE_SUBSCRIPTION_PRICE_RUB,
            period_days=VOICE_SUBSCRIPTION_DAYS,
            created_at=datetime.now(pytz.timezone(settings.TIMEZONE)),
        )
        await query.message.reply_text(
            format_voice_subscription_mock_payment(
                amount_rub=payment.amount_rub,
                period_days=payment.period_days,
            ),
            parse_mode="HTML",
            reply_markup=get_voice_subscription_mock_payment_keyboard(payment.id),
        )
        return

    if data.startswith("voice_sub:activate:"):
        payment_id = data.split(":", 2)[2]
        payment = await get_voice_subscription_payment(payment_id)
        if not payment or payment.user_id != update.effective_user.id:
            await query.message.reply_text(
                "Не нашёл эту заявку на подписку. Попробуй открыть покупку заново.",
                reply_markup=get_main_reply_keyboard(update.effective_user.id),
            )
            return

        if getattr(payment, "status", "pending") == "paid":
            access = await get_voice_input_access(update.effective_user)
            await query.message.reply_text(
                format_voice_subscription_already_active(access.subscription_expires_at),
                parse_mode="HTML",
                reply_markup=get_main_reply_keyboard(update.effective_user.id),
            )
            return

        await mark_voice_subscription_payment_paid(
            payment_id,
            paid_at=datetime.now(pytz.timezone(settings.TIMEZONE)),
        )
        access = await activate_voice_input_subscription(update.effective_user)
        await query.message.reply_text(
            format_voice_subscription_activated(access.subscription_expires_at),
            parse_mode="HTML",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )


async def handle_donation_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Consume free-form text while waiting for a custom Stars amount."""
    if not context.user_data.get(AWAITING_DONATION_AMOUNT_KEY):
        return False

    text = get_input_text(update, context, strip=True) or ""
    if not text:
        return True

    if text.lower() in _CUSTOM_CANCEL_VALUES:
        _clear_payment_states(context)
        await update.message.reply_text(
            "Шаг с суммой доната отменил.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    amount = _parse_donation_amount_text(text)
    if amount is None:
        await update.message.reply_text(
            format_donation_amount_invalid(),
            parse_mode="HTML",
        )
        return True

    _clear_payment_states(context)
    await _send_donation_invoice(update=update, context=context, amount=amount)
    return True


async def handle_cloudpayments_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Consume free-form text while waiting for an SBP amount."""
    if not context.user_data.get(AWAITING_SBP_AMOUNT_KEY):
        return False

    text = get_input_text(update, context, strip=True) or ""
    if not text:
        return True

    if text.lower() in _CUSTOM_CANCEL_VALUES:
        _clear_payment_states(context)
        await update.message.reply_text(
            "Шаг с оплатой по СБП отменил.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id),
        )
        return True

    return await _create_cloudpayments_sbp_payment(
        update=update,
        context=context,
        amount_text=text,
    )


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve Telegram Stars checkout for known donation payloads."""
    query = update.pre_checkout_query
    payload = query.invoice_payload

    if not _is_donation_payload(payload):
        await query.answer(ok=False, error_message="Не удалось обработать этот платёж.")
        return

    await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm a successful Telegram Stars donation and store charge ids."""
    message = update.effective_message
    payment = message.successful_payment if message else None
    if not payment or not _is_donation_payload(payment.invoice_payload):
        return

    await record_interaction(update.effective_user.id)

    tz = pytz.timezone(settings.TIMEZONE)
    await save_donation_payment(
        DonationPayment(
            user_id=update.effective_user.id,
            amount=payment.total_amount,
            currency=payment.currency,
            payload=payment.invoice_payload,
            telegram_payment_charge_id=payment.telegram_payment_charge_id,
            provider_payment_charge_id=payment.provider_payment_charge_id or "",
            created_at=datetime.now(tz),
        )
    )

    amount = _parse_amount_from_payload(payment.invoice_payload) or payment.total_amount
    await message.reply_text(
        format_donation_success(amount),
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard(update.effective_user.id),
    )


def get_payment_handlers() -> list:
    """Return command and payment handlers for the support flows."""
    return [
        CommandHandler("donate", donate_command),
        CommandHandler("paysupport", paysupport_command),
        PreCheckoutQueryHandler(precheckout_callback),
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback),
    ]
