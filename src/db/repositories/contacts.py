from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Optional
from uuid import UUID

from src.db.models import to_record, to_records
from src.db.repositories.base import BaseRepository


class ContactRepository(BaseRepository):
    TABLE = "bot_contacts"

    async def create(
        self,
        user_id: int,
        username: str,
        description: Optional[str] = None,
        display_name: Optional[str] = None,
        tags: Optional[list[str]] = None,
        reminder_frequency: str = "biweekly",
        custom_interval_days: Optional[int] = None,
        next_reminder_date: Optional[date] = None,
        one_time_date: Optional[date] = None,
        status: str = "active",
    ) -> SimpleNamespace:
        data = {
            "user_id": user_id,
            "username": username,
            "display_name": display_name,
            "description": description,
            "tags": tags or [],
            "reminder_frequency": reminder_frequency,
            "custom_interval_days": custom_interval_days,
            "next_reminder_date": next_reminder_date.isoformat() if next_reminder_date else None,
            "one_time_date": one_time_date.isoformat() if one_time_date else None,
            "status": status,
        }
        result = await self.client.table(self.TABLE).insert(data).execute()
        return to_record(result.data[0])

    async def get_by_id(self, contact_id) -> Optional[SimpleNamespace]:
        result = (
            await self.client.table(self.TABLE)
            .select("*")
            .eq("id", str(contact_id))
            .maybe_single()
            .execute()
        )
        return to_record(result.data) if result else None

    async def get_by_username(self, user_id: int, username: str) -> Optional[SimpleNamespace]:
        # Normalize username (remove @ if present)
        username = username.lstrip("@").lower()
        result = (
            await self.client.table(self.TABLE)
            .select("*")
            .eq("user_id", user_id)
            .ilike("username", username)
            .maybe_single()
            .execute()
        )
        return to_record(result.data) if result else None

    async def get_all_for_user(self, user_id: int) -> list[SimpleNamespace]:
        result = (
            await self.client.table(self.TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("next_reminder_date", nullsfirst=False)
            .execute()
        )
        return to_records(result.data)

    async def get_due_today(self, target_date: date) -> list[SimpleNamespace]:
        """Get all contacts that are due for reminder today"""
        result = (
            await self.client.table(self.TABLE)
            .select("*")
            .in_("status", ["active", "one_time"])
            .lte("next_reminder_date", target_date.isoformat())
            .execute()
        )
        return to_records(result.data)

    async def get_overdue_not_contacted(self, target_date: date) -> list[SimpleNamespace]:
        """Get contacts due today that haven't been marked as contacted today"""
        date_str = target_date.isoformat()
        result = (
            await self.client.table(self.TABLE)
            .select("*")
            .in_("status", ["active", "one_time"])
            .lte("next_reminder_date", date_str)
            .or_(f"last_contacted_at.is.null,last_contacted_at.lt.{date_str}")
            .execute()
        )
        return to_records(result.data)

    async def update(self, contact_id, **kwargs) -> SimpleNamespace:
        """Update a contact by ID. Accepts string or UUID for contact_id."""
        # Serialize date/datetime values
        data = {}
        for key, value in kwargs.items():
            if isinstance(value, (date, datetime)):
                data[key] = value.isoformat()
            else:
                data[key] = value
        result = (
            await self.client.table(self.TABLE)
            .update(data)
            .eq("id", str(contact_id))
            .execute()
        )
        return to_record(result.data[0])

    async def delete(self, contact_id) -> None:
        """Delete a contact by ID. Accepts string or UUID for contact_id."""
        await self.client.table(self.TABLE).delete().eq("id", str(contact_id)).execute()

    async def search_by_tags(self, user_id: int, tags: list[str]) -> list[SimpleNamespace]:
        """Search contacts by tags using PostgreSQL array overlap"""
        result = (
            await self.client.table(self.TABLE)
            .select("*")
            .eq("user_id", user_id)
            .overlaps("tags", tags)
            .execute()
        )
        return to_records(result.data)


    async def get_contacts_contacted_this_week(self, user_id: int) -> int:
        """Count contacts contacted in the last 7 days"""
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        result = (
            await self.client.table(self.TABLE)
            .select("id")
            .eq("user_id", user_id)
            .gte("last_contacted_at", week_ago)
            .execute()
        )
        return len(result.data)

    async def get_missed_reminders_this_week(self, user_id: int) -> int:
        """Count reminders that were due but not acted upon in the last 7 days"""
        today = date.today()
        week_ago = today - timedelta(days=7)

        result = (
            await self.client.table(self.TABLE)
            .select("*")
            .eq("user_id", user_id)
            .lt("next_reminder_date", today.isoformat())
            .gte("next_reminder_date", week_ago.isoformat())
            .execute()
        )
        # Filter in Python: last_contacted_at is null or before next_reminder_date
        records = to_records(result.data)
        count = 0
        for r in records:
            if r.last_contacted_at is None or (
                r.next_reminder_date and r.last_contacted_at < datetime.combine(r.next_reminder_date, datetime.min.time())
            ):
                count += 1
        return count

    async def get_all_unique_user_ids(self) -> list[int]:
        """Get all unique user_ids that have contacts (for weekly stats)."""
        result = await self.client.table(self.TABLE).select("user_id").execute()
        return list(set(row["user_id"] for row in result.data))
