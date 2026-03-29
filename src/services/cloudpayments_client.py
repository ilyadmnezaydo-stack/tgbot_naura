from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping
from urllib.parse import unquote_plus

import httpx


SBP_LINK_URL = "https://api.cloudpayments.ru/payments/qr/sbp/link"


class CloudPaymentsClientError(Exception):
    """Raised when the CloudPayments API rejects or fails a request."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_payload: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_payload = response_payload


@dataclass(slots=True)
class CloudPaymentsSbpLinkRequest:
    amount: Decimal
    currency: str
    invoice_id: str
    account_id: str
    description: str | None = None
    success_redirect_url: str | None = None
    ttl_minutes: int | None = None
    is_test: bool = False
    json_data: dict | None = None


@dataclass(slots=True)
class CloudPaymentsSbpLinkResponse:
    qr_url: str
    transaction_id: int | None
    provider_qr_id: str | None
    status: str | None
    amount: Decimal | None
    raw_response: dict


def _quantize_amount(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_cloudpayments_hmac(message: bytes | str, secret: str) -> str:
    """Build a base64-encoded HMAC-SHA256 signature for CloudPayments."""
    body = message if isinstance(message, bytes) else message.encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_cloudpayments_signature(
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    secret: str,
) -> bool:
    """Accept either CloudPayments signature header format for webhook requests."""
    content_hmac = headers.get("Content-HMAC") or headers.get("content-hmac") or ""
    x_content_hmac = headers.get("X-Content-HMAC") or headers.get("x-content-hmac") or ""

    if not content_hmac and not x_content_hmac:
        return False

    raw_signature = build_cloudpayments_hmac(raw_body, secret)
    decoded_signature = build_cloudpayments_hmac(unquote_plus(raw_body.decode("utf-8")), secret)

    return any(
        [
            bool(content_hmac and hmac.compare_digest(content_hmac, raw_signature)),
            bool(x_content_hmac and hmac.compare_digest(x_content_hmac, decoded_signature)),
            bool(x_content_hmac and hmac.compare_digest(x_content_hmac, raw_signature)),
        ]
    )


class CloudPaymentsClient:
    """Minimal async client for the CloudPayments SBP payment-link API."""

    def __init__(
        self,
        *,
        public_id: str,
        api_secret: str,
        timeout_seconds: int = 20,
    ) -> None:
        self.public_id = public_id
        self.api_secret = api_secret
        self.timeout_seconds = timeout_seconds

    async def create_sbp_payment_link(
        self,
        request: CloudPaymentsSbpLinkRequest,
    ) -> CloudPaymentsSbpLinkResponse:
        payload = {
            "PublicId": self.public_id,
            "Amount": float(_quantize_amount(request.amount)),
            "Currency": request.currency,
            "InvoiceId": request.invoice_id,
            "AccountId": request.account_id,
            "Scheme": "charge",
            "IsTest": request.is_test,
        }
        if request.description:
            payload["Description"] = request.description
        if request.success_redirect_url:
            payload["SuccessRedirectUrl"] = request.success_redirect_url
        if request.ttl_minutes:
            payload["TtlMinutes"] = request.ttl_minutes
        if request.json_data:
            payload["JsonData"] = request.json_data

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                SBP_LINK_URL,
                auth=(self.public_id, self.api_secret),
                json=payload,
            )

        try:
            parsed = response.json()
        except json.JSONDecodeError as exc:
            raise CloudPaymentsClientError(
                "CloudPayments returned a non-JSON response",
                status_code=response.status_code,
            ) from exc

        if response.status_code >= 400 or not parsed.get("Success"):
            raise CloudPaymentsClientError(
                parsed.get("Message") or "CloudPayments rejected the request",
                status_code=response.status_code,
                response_payload=parsed,
            )

        model = parsed.get("Model") or {}
        qr_url = str(model.get("QrUrl") or "").strip()
        if not qr_url:
            raise CloudPaymentsClientError(
                "CloudPayments didn't return an SBP payment link",
                status_code=response.status_code,
                response_payload=parsed,
            )

        amount = model.get("Amount")
        return CloudPaymentsSbpLinkResponse(
            qr_url=qr_url,
            transaction_id=int(model["TransactionId"]) if model.get("TransactionId") is not None else None,
            provider_qr_id=str(model.get("ProviderQrId") or "") or None,
            status=str(model.get("Message") or "") or None,
            amount=Decimal(str(amount)) if amount is not None else None,
            raw_response=parsed,
        )
