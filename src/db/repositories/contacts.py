from datetime import date, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, or_, select

from src.db.models import Contact, ContactHistory
from src.db.repositories.base import BaseRepository


class ContactRepository(BaseRepository):
    async def create(
        self,
        user_id: int,
        username: str,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
        reminder_frequency: str = "biweekly",
        custom_interval_days: Optional[int] = None,
        next_reminder_date: Optional[date] = None,
        one_time_date: Optional[date] = None,
        status: str = "active",
    ) -> Contact:
        contact = Contact(
            user_id=user_id,
            username=username,
            description=description,
            tags=tags or [],
            reminder_frequency=reminder_frequency,
            custom_interval_days=custom_interval_days,
            next_reminder_date=next_reminder_date,
            one_time_date=one_time_date,
            status=status,
        )
        self.session.add(contact)
        await self.session.commit()
        await self.session.refresh(contact)
        return contact

    async def get_by_id(self, contact_id: UUID) -> Optional[Contact]:
        result = await self.session.execute(
            select(Contact).where(Contact.id == contact_id)
        )
        return result.scalar_one_or_none()

    async def get_by_username(self, user_id: int, username: str) -> Optional[Contact]:
        # Normalize username (remove @ if present)
        username = username.lstrip("@").lower()
        result = await self.session.execute(
            select(Contact).where(
                and_(
                    Contact.user_id == user_id,
                    Contact.username.ilike(username),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_all_for_user(self, user_id: int) -> list[Contact]:
        result = await self.session.execute(
            select(Contact)
            .where(Contact.user_id == user_id)
            .order_by(Contact.next_reminder_date.asc().nullslast())
        )
        return list(result.scalars().all())

    async def get_due_today(self, target_date: date) -> list[Contact]:
        """Get all contacts that are due for reminder today"""
        result = await self.session.execute(
            select(Contact).where(
                and_(
                    Contact.status.in_(["active", "one_time"]),
                    Contact.next_reminder_date <= target_date,
                )
            )
        )
        return list(result.scalars().all())

    async def get_overdue_not_contacted(self, target_date: date) -> list[Contact]:
        """Get contacts due today that haven't been marked as contacted today"""
        result = await self.session.execute(
            select(Contact).where(
                and_(
                    Contact.status.in_(["active", "one_time"]),
                    Contact.next_reminder_date <= target_date,
                    or_(
                        Contact.last_contacted_at.is_(None),
                        Contact.last_contacted_at < datetime.combine(target_date, datetime.min.time()),
                    ),
                )
            )
        )
        return list(result.scalars().all())

    async def update(self, contact: Contact, **kwargs) -> Contact:
        for key, value in kwargs.items():
            if hasattr(contact, key):
                setattr(contact, key, value)
        await self.session.commit()
        await self.session.refresh(contact)
        return contact

    async def delete(self, contact: Contact) -> None:
        await self.session.delete(contact)
        await self.session.commit()

    async def search_by_tags(self, user_id: int, tags: list[str]) -> list[Contact]:
        """Search contacts by tags using PostgreSQL array overlap"""
        result = await self.session.execute(
            select(Contact).where(
                and_(
                    Contact.user_id == user_id,
                    Contact.tags.overlap(tags),
                )
            )
        )
        return list(result.scalars().all())

    async def add_history(
        self, contact_id: UUID, action: str, notes: Optional[str] = None
    ) -> ContactHistory:
        history = ContactHistory(
            contact_id=contact_id,
            action=action,
            notes=notes,
        )
        self.session.add(history)
        await self.session.commit()
        return history

    async def get_contacts_contacted_this_week(self, user_id: int) -> int:
        """Count contacts contacted in the last 7 days"""
        from datetime import timedelta

        week_ago = datetime.utcnow() - timedelta(days=7)
        result = await self.session.execute(
            select(Contact).where(
                and_(
                    Contact.user_id == user_id,
                    Contact.last_contacted_at >= week_ago,
                )
            )
        )
        return len(list(result.scalars().all()))

    async def get_missed_reminders_this_week(self, user_id: int) -> int:
        """Count reminders that were due but not acted upon in the last 7 days"""
        from datetime import timedelta

        today = date.today()
        week_ago = today - timedelta(days=7)

        result = await self.session.execute(
            select(Contact).where(
                and_(
                    Contact.user_id == user_id,
                    Contact.next_reminder_date < today,
                    Contact.next_reminder_date >= week_ago,
                    or_(
                        Contact.last_contacted_at.is_(None),
                        Contact.last_contacted_at < datetime.combine(
                            Contact.next_reminder_date, datetime.min.time()
                        ),
                    ),
                )
            )
        )
        return len(list(result.scalars().all()))
