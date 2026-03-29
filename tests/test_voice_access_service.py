import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytz

from src.services.voice_access_service import (
    VoiceAccessState,
    activate_voice_input_subscription,
    ensure_voice_input_access,
)


class VoiceAccessServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_voice_use_starts_trial(self) -> None:
        now = datetime(2026, 3, 28, 12, 0, tzinfo=pytz.UTC)
        telegram_user = SimpleNamespace(id=42, username="tester", first_name="Test")
        created_user = SimpleNamespace(id=42, voice_trial_started_at=None, voice_trial_expires_at=None, voice_subscription_expires_at=None)
        updated_user = SimpleNamespace(
            id=42,
            voice_trial_started_at=now,
            voice_trial_expires_at=now + timedelta(days=14),
            voice_subscription_expires_at=None,
        )
        repo = SimpleNamespace(
            get_or_create=AsyncMock(return_value=created_user),
            update=AsyncMock(return_value=updated_user),
        )

        with (
            patch("src.services.voice_access_service._repo", AsyncMock(return_value=repo)),
            patch("src.services.voice_access_service._now", return_value=now),
        ):
            state = await ensure_voice_input_access(telegram_user)

        self.assertTrue(state.has_access)
        self.assertEqual(state.access_type, "trial_started")
        repo.update.assert_awaited_once()

    async def test_expired_trial_blocks_voice_input(self) -> None:
        now = datetime(2026, 3, 28, 12, 0, tzinfo=pytz.UTC)
        telegram_user = SimpleNamespace(id=42, username="tester", first_name="Test")
        existing_user = SimpleNamespace(
            id=42,
            voice_trial_started_at=now - timedelta(days=20),
            voice_trial_expires_at=now - timedelta(days=6),
            voice_subscription_expires_at=None,
        )
        repo = SimpleNamespace(
            get_or_create=AsyncMock(return_value=existing_user),
            update=AsyncMock(),
        )

        with (
            patch("src.services.voice_access_service._repo", AsyncMock(return_value=repo)),
            patch("src.services.voice_access_service._now", return_value=now),
        ):
            state = await ensure_voice_input_access(telegram_user)

        self.assertFalse(state.has_access)
        self.assertEqual(state.access_type, "expired")
        repo.update.assert_not_called()

    async def test_paid_subscription_extends_from_current_expiry(self) -> None:
        now = datetime(2026, 3, 28, 12, 0, tzinfo=pytz.UTC)
        telegram_user = SimpleNamespace(id=42, username="tester", first_name="Test")
        existing_user = SimpleNamespace(
            id=42,
            voice_trial_started_at=None,
            voice_trial_expires_at=None,
            voice_subscription_expires_at=now + timedelta(days=10),
        )
        updated_user = SimpleNamespace(
            id=42,
            voice_trial_started_at=None,
            voice_trial_expires_at=None,
            voice_subscription_expires_at=now + timedelta(days=40),
        )
        repo = SimpleNamespace(
            get_or_create=AsyncMock(return_value=existing_user),
            update=AsyncMock(return_value=updated_user),
        )

        with (
            patch("src.services.voice_access_service._repo", AsyncMock(return_value=repo)),
            patch("src.services.voice_access_service._now", return_value=now),
        ):
            state = await activate_voice_input_subscription(telegram_user)

        self.assertTrue(state.has_access)
        self.assertEqual(state.access_type, "paid_active")
        repo.update.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
