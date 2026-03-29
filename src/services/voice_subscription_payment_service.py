"""
Mock persistence for voice-input subscription payments.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4


@dataclass(slots=True)
class VoiceSubscriptionPayment:
    """One mocked payment request for voice-input access."""

    id: str
    user_id: int
    amount_rub: int
    period_days: int
    status: str
    created_at: datetime
    paid_at: datetime | None = None


_STORE_LOCK = asyncio.Lock()
_STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "voice_subscription_payments.json"


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


def _to_payment(raw: dict) -> VoiceSubscriptionPayment | None:
    try:
        created_at = datetime.fromisoformat(str(raw["created_at"]))
        paid_at_raw = raw.get("paid_at")
        paid_at = datetime.fromisoformat(str(paid_at_raw)) if paid_at_raw else None
        return VoiceSubscriptionPayment(
            id=str(raw["id"]),
            user_id=int(raw["user_id"]),
            amount_rub=int(raw["amount_rub"]),
            period_days=int(raw["period_days"]),
            status=str(raw["status"]),
            created_at=created_at,
            paid_at=paid_at,
        )
    except (KeyError, TypeError, ValueError):
        return None


async def create_mock_voice_subscription_payment(
    *,
    user_id: int,
    amount_rub: int,
    period_days: int,
    created_at: datetime,
) -> VoiceSubscriptionPayment:
    """Create and persist a pending mocked payment request."""
    payment = VoiceSubscriptionPayment(
        id=uuid4().hex[:12],
        user_id=user_id,
        amount_rub=amount_rub,
        period_days=period_days,
        status="pending",
        created_at=created_at,
    )
    raw_payment = {
        "id": payment.id,
        "user_id": payment.user_id,
        "amount_rub": payment.amount_rub,
        "period_days": payment.period_days,
        "status": payment.status,
        "created_at": payment.created_at.isoformat(),
        "paid_at": None,
    }

    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)
        data.insert(0, raw_payment)
        await asyncio.to_thread(_write_store, data)

    return payment


async def get_voice_subscription_payment(payment_id: str) -> VoiceSubscriptionPayment | None:
    """Load one mocked payment request by id."""
    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)

    for raw in data:
        if not isinstance(raw, dict) or raw.get("id") != payment_id:
            continue
        return _to_payment(raw)
    return None


async def mark_voice_subscription_payment_paid(
    payment_id: str,
    *,
    paid_at: datetime,
) -> VoiceSubscriptionPayment | None:
    """Mark a mocked payment as paid if it wasn't paid already."""
    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)
        updated_payment: VoiceSubscriptionPayment | None = None

        for raw in data:
            if not isinstance(raw, dict) or raw.get("id") != payment_id:
                continue
            raw["status"] = "paid"
            raw["paid_at"] = paid_at.isoformat()
            updated_payment = _to_payment(raw)
            break

        if updated_payment is None:
            return None

        await asyncio.to_thread(_write_store, data)
        return updated_payment
