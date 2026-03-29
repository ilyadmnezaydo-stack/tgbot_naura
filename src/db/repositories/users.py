from types import SimpleNamespace
from typing import Optional
from datetime import date, datetime

from src.db.models import to_record, to_records
from src.db.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    TABLE = "bot_users"

    async def update(self, user_id: int, **kwargs) -> SimpleNamespace:
        """Update one user row, serializing date-like fields when needed."""
        data = {}
        for key, value in kwargs.items():
            if isinstance(value, (date, datetime)):
                data[key] = value.isoformat()
            else:
                data[key] = value

        result = await self.client.table(self.TABLE).update(data).eq("id", user_id).execute()
        return to_record(result.data[0])

    async def get_by_id(self, user_id: int) -> Optional[SimpleNamespace]:
        result = await self.client.table(self.TABLE).select("*").eq("id", user_id).maybe_single().execute()
        return to_record(result.data) if result else None

    async def get_or_create(
        self,
        user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        language_code: str = "ru",
    ) -> SimpleNamespace:
        user = await self.get_by_id(user_id)
        if user:
            # Update user info if changed
            updates = {}
            if username and user.username != username:
                updates["username"] = username
            if first_name and user.first_name != first_name:
                updates["first_name"] = first_name
            if updates:
                result = await self.client.table(self.TABLE).update(updates).eq("id", user_id).execute()
                return to_record(result.data[0])
            return user

        # Create new user
        data = {
            "id": user_id,
            "username": username,
            "first_name": first_name,
            "language_code": language_code,
        }
        result = await self.client.table(self.TABLE).insert(data).execute()
        return to_record(result.data[0])

    async def get_all_user_ids(self) -> list[int]:
        """Get all user IDs for batch operations like reminders"""
        result = await self.client.table(self.TABLE).select("id").execute()
        return [row["id"] for row in (result.data or [])]

    async def get_all(self) -> list[SimpleNamespace]:
        """Return all registered bot users."""
        result = await self.client.table(self.TABLE).select("*").execute()
        return to_records(result.data or [])

    async def count_all_users(self) -> int:
        """Return the total number of users registered in the bot."""
        return len(await self.get_all_user_ids())
