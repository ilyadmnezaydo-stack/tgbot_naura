"""
Local storage for successful Telegram Stars donations.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class DonationPayment:
    """A successful Telegram Stars donation."""

    user_id: int
    amount: int
    currency: str
    payload: str
    telegram_payment_charge_id: str
    provider_payment_charge_id: str
    created_at: datetime


_STORE_LOCK = asyncio.Lock()
_STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "support_payments.json"


def _ensure_store_dir() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_store() -> list[dict]:
    if not _STORE_PATH.exists():
        return []

    try:
        with _STORE_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_store(data: list[dict]) -> None:
    _ensure_store_dir()
    temp_path = _STORE_PATH.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    temp_path.replace(_STORE_PATH)


def _to_payment(raw: dict) -> DonationPayment | None:
    created_at = raw.get("created_at")
    if not created_at:
        return None

    try:
        parsed_created_at = datetime.fromisoformat(created_at)
        user_id = int(raw["user_id"])
        amount = int(raw["amount"])
    except (KeyError, TypeError, ValueError):
        return None

    return DonationPayment(
        user_id=user_id,
        amount=amount,
        currency=str(raw.get("currency") or "XTR"),
        payload=str(raw.get("payload") or ""),
        telegram_payment_charge_id=str(raw.get("telegram_payment_charge_id") or ""),
        provider_payment_charge_id=str(raw.get("provider_payment_charge_id") or ""),
        created_at=parsed_created_at,
    )


async def list_donation_payments() -> list[DonationPayment]:
    """Return all successful Telegram Stars payments."""
    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)

    payments: list[DonationPayment] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        payment = _to_payment(raw)
        if payment:
            payments.append(payment)

    payments.sort(key=lambda item: item.created_at, reverse=True)
    return payments


async def save_donation_payment(payment: DonationPayment) -> None:
    """Persist a successful Stars payment for later support/refund handling."""
    raw_payment = {
        "user_id": payment.user_id,
        "amount": payment.amount,
        "currency": payment.currency,
        "payload": payment.payload,
        "telegram_payment_charge_id": payment.telegram_payment_charge_id,
        "provider_payment_charge_id": payment.provider_payment_charge_id,
        "created_at": payment.created_at.isoformat(),
    }

    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)
        data.insert(0, raw_payment)
        await asyncio.to_thread(_write_store, data)
