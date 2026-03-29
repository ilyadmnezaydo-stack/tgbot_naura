"""
Voice-input monetization message templates.
"""
from __future__ import annotations

from datetime import datetime

import pytz

from src.config import settings


def _format_local_datetime(value: datetime | None) -> str | None:
    """Format one datetime in the bot timezone."""
    if not value:
        return None
    tz = pytz.timezone(settings.TIMEZONE)
    localized = value.astimezone(tz) if value.tzinfo else tz.localize(value)
    return localized.strftime("%d.%m.%Y")


def format_voice_trial_started(trial_expires_at: datetime | None) -> str:
    """Explain that the first voice input started the free trial."""
    expires_at_text = _format_local_datetime(trial_expires_at) or "через 14 дней"
    return (
        "🎙 <b>Голосовой ввод активирован</b>\n\n"
        f"Включил бесплатный trial на 14 дней. Он действует до <b>{expires_at_text}</b>.\n"
        "Пока можно пользоваться голосовыми сообщениями без ограничений."
    )


def format_voice_subscription_offer(
    *,
    trial_expires_at: datetime | None,
    price_rub: int,
) -> str:
    """Offer a paid monthly plan after the voice trial ends."""
    expires_at_text = _format_local_datetime(trial_expires_at) or "недавно"
    return (
        "🎙 <b>Триал на голосовой ввод закончился</b>\n\n"
        f"Пробный доступ закончился <b>{expires_at_text}</b>.\n"
        f"Чтобы продолжить пользоваться голосовым вводом, можно подключить подписку за <b>{price_rub} ₽ в месяц</b>."
    )


def format_voice_subscription_mock_payment(
    *,
    amount_rub: int,
    period_days: int,
) -> str:
    """Explain the mocked payment flow for voice-input access."""
    return (
        "🏦 <b>Подписка на голосовой ввод</b>\n\n"
        f"Тариф: <b>{amount_rub} ₽</b> за <b>{period_days} дней</b>.\n"
        "Сейчас это моковая оплата для теста сценария, без реального списания.\n\n"
        "Нажми кнопку ниже, и я сразу активирую подписку."
    )


def format_voice_subscription_activated(subscription_expires_at: datetime | None) -> str:
    """Confirm that voice-input access is active after mocked payment."""
    expires_at_text = _format_local_datetime(subscription_expires_at) or "через 30 дней"
    return (
        "✅ <b>Подписка на голосовой ввод активна</b>\n\n"
        f"Доступ открыт до <b>{expires_at_text}</b>.\n"
        "Теперь голосовые сообщения снова можно отправлять как обычно."
    )


def format_voice_subscription_already_active(subscription_expires_at: datetime | None) -> str:
    """Explain that a user already has active voice-input access."""
    expires_at_text = _format_local_datetime(subscription_expires_at) or "позже"
    return (
        "🎙 Голосовой ввод уже активен.\n"
        f"Текущий доступ действует до <b>{expires_at_text}</b>."
    )
