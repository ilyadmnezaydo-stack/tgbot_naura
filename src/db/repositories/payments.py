from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional

from src.db.models import to_record, to_records
from src.db.repositories.base import BaseRepository


class PaymentRepository(BaseRepository):
    TABLE = "bot_payments"

    async def create(
        self,
        *,
        invoice_id: str,
        user_id: int,
        provider: str,
        payment_method: str,
        status: str,
        amount: Decimal,
        currency: str,
        description: str | None = None,
        account_id: str | None = None,
        provider_transaction_id: int | None = None,
        provider_qr_id: str | None = None,
        payment_url: str | None = None,
        provider_status: str | None = None,
        failure_reason: str | None = None,
        failure_reason_code: int | None = None,
        raw_create_response: dict | None = None,
        raw_last_webhook: dict | None = None,
        last_webhook_type: str | None = None,
        paid_at: datetime | None = None,
        failed_at: datetime | None = None,
        canceled_at: datetime | None = None,
        expired_at: datetime | None = None,
        notified_paid_at: datetime | None = None,
    ) -> SimpleNamespace:
        data = {
            "invoice_id": invoice_id,
            "user_id": user_id,
            "provider": provider,
            "payment_method": payment_method,
            "status": status,
            "amount": str(amount),
            "currency": currency,
            "description": description,
            "account_id": account_id,
            "provider_transaction_id": provider_transaction_id,
            "provider_qr_id": provider_qr_id,
            "payment_url": payment_url,
            "provider_status": provider_status,
            "failure_reason": failure_reason,
            "failure_reason_code": failure_reason_code,
            "raw_create_response": raw_create_response,
            "raw_last_webhook": raw_last_webhook,
            "last_webhook_type": last_webhook_type,
            "paid_at": paid_at.isoformat() if paid_at else None,
            "failed_at": failed_at.isoformat() if failed_at else None,
            "canceled_at": canceled_at.isoformat() if canceled_at else None,
            "expired_at": expired_at.isoformat() if expired_at else None,
            "notified_paid_at": notified_paid_at.isoformat() if notified_paid_at else None,
        }
        result = await self.client.table(self.TABLE).insert(data).execute()
        return to_record(result.data[0])

    async def get_by_id(self, payment_id: str) -> Optional[SimpleNamespace]:
        result = (
            await self.client.table(self.TABLE)
            .select("*")
            .eq("id", str(payment_id))
            .maybe_single()
            .execute()
        )
        return to_record(result.data) if result else None

    async def get_by_invoice_id(self, invoice_id: str) -> Optional[SimpleNamespace]:
        result = (
            await self.client.table(self.TABLE)
            .select("*")
            .eq("invoice_id", invoice_id)
            .maybe_single()
            .execute()
        )
        return to_record(result.data) if result else None

    async def list_all(self) -> list[SimpleNamespace]:
        result = (
            await self.client.table(self.TABLE)
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        return to_records(result.data or [])

    async def update(self, payment_id: str, **kwargs) -> SimpleNamespace:
        data = {}
        for key, value in kwargs.items():
            if isinstance(value, (date, datetime)):
                data[key] = value.isoformat()
            elif isinstance(value, Decimal):
                data[key] = str(value)
            else:
                data[key] = value
        result = (
            await self.client.table(self.TABLE)
            .update(data)
            .eq("id", str(payment_id))
            .execute()
        )
        return to_record(result.data[0])

    async def mark_paid_if_not_paid(self, payment_id: str, **kwargs) -> Optional[SimpleNamespace]:
        data = {}
        for key, value in kwargs.items():
            if isinstance(value, (date, datetime)):
                data[key] = value.isoformat()
            elif isinstance(value, Decimal):
                data[key] = str(value)
            else:
                data[key] = value
        result = (
            await self.client.table(self.TABLE)
            .update(data)
            .eq("id", str(payment_id))
            .neq("status", "paid")
            .execute()
        )
        rows = result.data or []
        return to_record(rows[0]) if rows else None

    async def mark_failed_if_not_paid(self, payment_id: str, **kwargs) -> Optional[SimpleNamespace]:
        data = {}
        for key, value in kwargs.items():
            if isinstance(value, (date, datetime)):
                data[key] = value.isoformat()
            elif isinstance(value, Decimal):
                data[key] = str(value)
            else:
                data[key] = value
        result = (
            await self.client.table(self.TABLE)
            .update(data)
            .eq("id", str(payment_id))
            .neq("status", "paid")
            .execute()
        )
        rows = result.data or []
        return to_record(rows[0]) if rows else None
