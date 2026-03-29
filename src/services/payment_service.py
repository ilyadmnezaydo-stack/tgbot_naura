from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from types import SimpleNamespace
from urllib.parse import parse_qsl
from uuid import uuid4

import pytz

from src.config import settings
from src.db.engine import get_supabase
from src.db.repositories.payments import PaymentRepository
from src.db.repositories.users import UserRepository
from src.services.cloudpayments_client import (
    CloudPaymentsClient,
    CloudPaymentsClientError,
    CloudPaymentsSbpLinkRequest,
    verify_cloudpayments_signature,
)
from src.services.payment_notification_service import notify_user_about_successful_payment

logger = logging.getLogger(__name__)

PAYMENT_PROVIDER_CLOUDPAYMENTS = "cloudpayments"
PAYMENT_METHOD_SBP = "sbp"
PAYMENT_STATUS_PENDING = "pending"
PAYMENT_STATUS_PAID = "paid"
PAYMENT_STATUS_FAILED = "failed"
PAYMENT_STATUS_CANCELED = "canceled"
PAYMENT_STATUS_EXPIRED = "expired"


class PaymentConfigurationError(RuntimeError):
    """Raised when payment settings are missing in the environment."""


def _now() -> datetime:
    return datetime.now(pytz.timezone(settings.TIMEZONE))


def _quantize_amount(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_rub_amount_text(text: str | None) -> Decimal | None:
    """Parse a human-entered RUB amount like '1000', '1 000', or '1 499,90'."""
    if not text:
        return None

    normalized = text.strip().lower()
    for token in ("руб.", "руб", "rur", "rub", "₽", "р"):
        normalized = normalized.replace(token, "")
    normalized = normalized.replace(" ", "").replace("_", "").replace(",", ".")

    if normalized.count(".") > 1:
        return None

    try:
        amount = Decimal(normalized)
    except InvalidOperation:
        return None

    if amount <= 0:
        return None

    return _quantize_amount(amount)


def parse_cloudpayments_payload(raw_body: bytes, content_type: str | None = None) -> dict:
    """Support form-urlencoded CloudPayments webhooks and JSON test calls."""
    body_text = raw_body.decode("utf-8").strip()
    if not body_text:
        return {}

    if (content_type and "json" in content_type.lower()) or body_text.startswith("{"):
        try:
            parsed = json.loads(body_text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    payload: dict[str, object] = {}
    for key, value in parse_qsl(body_text, keep_blank_values=True):
        if key in {"Data", "JsonData", "CustomFields"}:
            try:
                payload[key] = json.loads(value)
                continue
            except json.JSONDecodeError:
                pass
        payload[key] = value
    return payload


def _decimal_from_payload(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return _quantize_amount(Decimal(str(value)))
    except InvalidOperation:
        return None


def _int_from_payload(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class SbpPaymentLinkResult:
    payment: SimpleNamespace
    payment_url: str


class PaymentService:
    """Business logic for CloudPayments SBP creation and webhook processing."""

    def __init__(self) -> None:
        if not settings.cloudpayments_enabled:
            raise PaymentConfigurationError(
                "CloudPayments is not configured. Fill CLOUDPAYMENTS_PUBLIC_ID and CLOUDPAYMENTS_API_SECRET."
            )
        self.client = CloudPaymentsClient(
            public_id=settings.CLOUDPAYMENTS_PUBLIC_ID,
            api_secret=settings.CLOUDPAYMENTS_API_SECRET,
            timeout_seconds=settings.CLOUDPAYMENTS_TIMEOUT_SECONDS,
        )

    async def _repos(self) -> tuple[UserRepository, PaymentRepository]:
        supabase = await get_supabase()
        return UserRepository(supabase), PaymentRepository(supabase)

    async def create_sbp_payment(
        self,
        *,
        telegram_user,
        amount: Decimal,
        description: str | None = None,
    ) -> SbpPaymentLinkResult:
        user_repo, payment_repo = await self._repos()
        await user_repo.get_or_create(
            user_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
        )

        invoice_id = f"sbp_{uuid4().hex}"
        account_id = str(telegram_user.id)
        clean_amount = _quantize_amount(amount)
        payment = await payment_repo.create(
            invoice_id=invoice_id,
            user_id=telegram_user.id,
            provider=PAYMENT_PROVIDER_CLOUDPAYMENTS,
            payment_method=PAYMENT_METHOD_SBP,
            status=PAYMENT_STATUS_PENDING,
            amount=clean_amount,
            currency=settings.CLOUDPAYMENTS_SBP_CURRENCY,
            description=description or "Поддержка проекта через Telegram-бот",
            account_id=account_id,
        )

        request = CloudPaymentsSbpLinkRequest(
            amount=clean_amount,
            currency=settings.CLOUDPAYMENTS_SBP_CURRENCY,
            invoice_id=invoice_id,
            account_id=account_id,
            description=payment.description,
            success_redirect_url=settings.CLOUDPAYMENTS_SUCCESS_REDIRECT_URL or None,
            ttl_minutes=settings.CLOUDPAYMENTS_SBP_TTL_MINUTES,
            is_test=settings.CLOUDPAYMENTS_TEST_MODE,
            json_data={
                "cloudpayments": {
                    "comment": "telegram_bot_support",
                    "nick": telegram_user.username or "",
                }
            },
        )

        try:
            provider_result = await self.client.create_sbp_payment_link(request)
        except CloudPaymentsClientError as exc:
            await payment_repo.update(
                payment.id,
                status=PAYMENT_STATUS_FAILED,
                failure_reason=str(exc),
                raw_create_response=exc.response_payload,
                failed_at=_now(),
            )
            raise

        payment = await payment_repo.update(
            payment.id,
            provider_transaction_id=provider_result.transaction_id,
            provider_qr_id=provider_result.provider_qr_id,
            payment_url=provider_result.qr_url,
            provider_status=provider_result.status,
            raw_create_response=provider_result.raw_response,
        )
        return SbpPaymentLinkResult(payment=payment, payment_url=provider_result.qr_url)

    async def process_check_webhook(self, *, payload: dict, raw_body: bytes, headers) -> int:
        self._verify_signature(raw_body=raw_body, headers=headers)

        payment = await self._load_payment_from_payload(payload)
        if not payment:
            return 10

        validation_code = self._validate_payload_against_payment(payment, payload)
        if validation_code is not None:
            return validation_code

        if payment.status in {PAYMENT_STATUS_CANCELED, PAYMENT_STATUS_EXPIRED}:
            return 20

        payment_repo = PaymentRepository(await get_supabase())
        await payment_repo.update(
            payment.id,
            raw_last_webhook=payload,
            last_webhook_type="check",
        )
        return 0

    async def process_pay_webhook(self, *, payload: dict, raw_body: bytes, headers) -> None:
        self._verify_signature(raw_body=raw_body, headers=headers)

        payment = await self._load_payment_from_payload(payload)
        if not payment:
            logger.warning("CloudPayments PAY webhook received for unknown invoice: %s", payload.get("InvoiceId"))
            return

        validation_code = self._validate_payload_against_payment(payment, payload)
        if validation_code is not None:
            logger.error(
                "CloudPayments PAY webhook validation failed for invoice %s with code %s",
                payment.invoice_id,
                validation_code,
            )
            return

        payment_repo = PaymentRepository(await get_supabase())
        updated = await payment_repo.mark_paid_if_not_paid(
            payment.id,
            status=PAYMENT_STATUS_PAID,
            provider_transaction_id=_int_from_payload(payload.get("TransactionId")) or payment.provider_transaction_id,
            provider_status="paid",
            raw_last_webhook=payload,
            last_webhook_type="pay",
            failure_reason=None,
            failure_reason_code=None,
            paid_at=_now(),
        )
        if not updated:
            return

        notified = await notify_user_about_successful_payment(
            telegram_user_id=updated.user_id,
            amount=updated.amount,
            currency=updated.currency,
        )
        if notified:
            await payment_repo.update(updated.id, notified_paid_at=_now())

    async def process_fail_webhook(self, *, payload: dict, raw_body: bytes, headers) -> None:
        self._verify_signature(raw_body=raw_body, headers=headers)

        payment = await self._load_payment_from_payload(payload)
        if not payment:
            logger.warning("CloudPayments FAIL webhook received for unknown invoice: %s", payload.get("InvoiceId"))
            return

        validation_code = self._validate_payload_against_payment(payment, payload)
        if validation_code is not None:
            logger.error(
                "CloudPayments FAIL webhook validation failed for invoice %s with code %s",
                payment.invoice_id,
                validation_code,
            )
            return

        payment_repo = PaymentRepository(await get_supabase())
        await payment_repo.mark_failed_if_not_paid(
            payment.id,
            status=PAYMENT_STATUS_FAILED,
            provider_transaction_id=_int_from_payload(payload.get("TransactionId")) or payment.provider_transaction_id,
            provider_status="failed",
            failure_reason=str(payload.get("Reason") or "") or None,
            failure_reason_code=_int_from_payload(payload.get("ReasonCode")),
            raw_last_webhook=payload,
            last_webhook_type="fail",
            failed_at=_now(),
        )

    def _verify_signature(self, *, raw_body: bytes, headers) -> None:
        if not verify_cloudpayments_signature(
            raw_body=raw_body,
            headers=headers,
            secret=settings.CLOUDPAYMENTS_API_SECRET,
        ):
            raise ValueError("Invalid CloudPayments signature")

    async def _load_payment_from_payload(self, payload: dict) -> SimpleNamespace | None:
        invoice_id = str(payload.get("InvoiceId") or "").strip()
        if not invoice_id:
            return None
        payment_repo = PaymentRepository(await get_supabase())
        return await payment_repo.get_by_invoice_id(invoice_id)

    def _validate_payload_against_payment(self, payment: SimpleNamespace, payload: dict) -> int | None:
        amount = _decimal_from_payload(payload.get("Amount"))
        currency = str(payload.get("Currency") or "").upper()
        account_id = str(payload.get("AccountId") or "").strip()

        if not account_id or account_id != str(payment.account_id or payment.user_id):
            return 11
        if amount is None or amount != payment.amount:
            return 12
        if not currency or currency != str(payment.currency).upper():
            return 12
        return None
