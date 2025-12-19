from typing import Optional

from sqlalchemy import select

from src.db.models import User
from src.db.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    async def get_by_id(self, user_id: int) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        language_code: str = "ru",
    ) -> User:
        user = await self.get_by_id(user_id)
        if user:
            # Update user info if changed
            if username and user.username != username:
                user.username = username
            if first_name and user.first_name != first_name:
                user.first_name = first_name
            await self.session.commit()
            return user

        # Create new user
        user = User(
            id=user_id,
            username=username,
            first_name=first_name,
            language_code=language_code,
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_all_user_ids(self) -> list[int]:
        """Get all user IDs for batch operations like reminders"""
        result = await self.session.execute(select(User.id))
        return [row[0] for row in result.fetchall()]
