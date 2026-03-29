from __future__ import annotations

import logging

from telegram import Bot

from src.bot.messages import format_cloudpayments_success
from src.config import settings

logger = logging.getLogger(__name__)


async def notify_user_about_successful_payment(*, telegram_user_id: int, amount, currency: str) -> bool:
    """Send one Telegram confirmation after a payment is marked as paid."""
    try:
        async with Bot(token=settings.TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(
                chat_id=telegram_user_id,
                text=format_cloudpayments_success(amount=amount, currency=currency),
                parse_mode="HTML",
            )
        return True
    except Exception:
        logger.exception("Failed to notify user %s about successful payment", telegram_user_id)
        return False
