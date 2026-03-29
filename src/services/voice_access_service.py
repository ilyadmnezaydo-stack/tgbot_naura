"""
Voice-input access control: trial and paid subscription state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytz

from src.config import settings
from src.db.engine import get_supabase
from src.db.repositories.users import UserRepository

VOICE_TRIAL_DAYS = 14
VOICE_SUBSCRIPTION_DAYS = 30
VOICE_SUBSCRIPTION_PRICE_RUB = 399


@dataclass(slots=True)
class VoiceAccessState:
    """Current voice-input access state for one Telegram user."""

    has_access: bool
    access_type: str
    trial_started_at: datetime | None = None
    trial_expires_at: datetime | None = None
    subscription_expires_at: datetime | None = None


def _now() -> datetime:
    return datetime.now(pytz.timezone(settings.TIMEZONE))


async def _repo() -> UserRepository:
    return UserRepository(await get_supabase())


def _build_state(user, *, has_access: bool, access_type: str) -> VoiceAccessState:
    return VoiceAccessState(
        has_access=has_access,
        access_type=access_type,
        trial_started_at=getattr(user, "voice_trial_started_at", None),
        trial_expires_at=getattr(user, "voice_trial_expires_at", None),
        subscription_expires_at=getattr(user, "voice_subscription_expires_at", None),
    )


async def ensure_voice_input_access(telegram_user) -> VoiceAccessState:
    """Grant the initial trial on first voice use, otherwise return current access."""
    repo = await _repo()
    user = await repo.get_or_create(
        user_id=telegram_user.id,
        username=telegram_user.username,
        first_name=telegram_user.first_name,
    )
    now = _now()

    subscription_expires_at = getattr(user, "voice_subscription_expires_at", None)
    if subscription_expires_at and subscription_expires_at > now:
        return _build_state(user, has_access=True, access_type="paid_active")

    trial_started_at = getattr(user, "voice_trial_started_at", None)
    trial_expires_at = getattr(user, "voice_trial_expires_at", None)
    if not trial_started_at or not trial_expires_at:
        user = await repo.update(
            user.id,
            voice_trial_started_at=now,
            voice_trial_expires_at=now + timedelta(days=VOICE_TRIAL_DAYS),
        )
        return _build_state(user, has_access=True, access_type="trial_started")

    if trial_expires_at > now:
        return _build_state(user, has_access=True, access_type="trial_active")

    return _build_state(user, has_access=False, access_type="expired")


async def get_voice_input_access(telegram_user) -> VoiceAccessState:
    """Read the current access state without auto-starting a trial."""
    repo = await _repo()
    user = await repo.get_or_create(
        user_id=telegram_user.id,
        username=telegram_user.username,
        first_name=telegram_user.first_name,
    )
    now = _now()

    subscription_expires_at = getattr(user, "voice_subscription_expires_at", None)
    if subscription_expires_at and subscription_expires_at > now:
        return _build_state(user, has_access=True, access_type="paid_active")

    trial_expires_at = getattr(user, "voice_trial_expires_at", None)
    if trial_expires_at and trial_expires_at > now:
        return _build_state(user, has_access=True, access_type="trial_active")

    if getattr(user, "voice_trial_started_at", None):
        return _build_state(user, has_access=False, access_type="expired")

    return _build_state(user, has_access=False, access_type="not_started")


async def activate_voice_input_subscription(telegram_user) -> VoiceAccessState:
    """Activate or extend paid voice-input access for one billing period."""
    repo = await _repo()
    user = await repo.get_or_create(
        user_id=telegram_user.id,
        username=telegram_user.username,
        first_name=telegram_user.first_name,
    )
    now = _now()
    current_expires_at = getattr(user, "voice_subscription_expires_at", None)
    trial_expires_at = getattr(user, "voice_trial_expires_at", None)
    active_candidates = [
        value
        for value in (current_expires_at, trial_expires_at, now)
        if value is not None
    ]
    base_time = max(active_candidates)

    user = await repo.update(
        user.id,
        voice_subscription_expires_at=base_time + timedelta(days=VOICE_SUBSCRIPTION_DAYS),
    )
    return _build_state(user, has_access=True, access_type="paid_active")
