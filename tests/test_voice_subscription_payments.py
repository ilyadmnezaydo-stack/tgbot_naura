import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.bot.handlers.payments import handle_voice_subscription_callback


class VoiceSubscriptionPaymentTests(unittest.IsolatedAsyncioTestCase):
    async def test_buy_callback_creates_mock_payment(self) -> None:
        query = SimpleNamespace(data="voice_sub:buy", answer=AsyncMock(), message=SimpleNamespace(reply_text=AsyncMock()))
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=42, username="tester", first_name="Test"),
            effective_chat=SimpleNamespace(type="private"),
        )
        context = SimpleNamespace()
        access = SimpleNamespace(has_access=False, subscription_expires_at=None)
        payment = SimpleNamespace(id="abc123", amount_rub=399, period_days=30)

        with (
            patch("src.bot.handlers.payments.record_interaction", AsyncMock()),
            patch("src.bot.handlers.payments.get_voice_input_access", AsyncMock(return_value=access)),
            patch("src.bot.handlers.payments.create_mock_voice_subscription_payment", AsyncMock(return_value=payment)),
        ):
            await handle_voice_subscription_callback(update, context)

        query.message.reply_text.assert_awaited_once()

    async def test_activate_callback_grants_access(self) -> None:
        query = SimpleNamespace(
            data="voice_sub:activate:abc123",
            answer=AsyncMock(),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=42, username="tester", first_name="Test"),
            effective_chat=SimpleNamespace(type="private"),
        )
        context = SimpleNamespace()
        payment = SimpleNamespace(id="abc123", user_id=42)
        access = SimpleNamespace(subscription_expires_at=None)

        with (
            patch("src.bot.handlers.payments.record_interaction", AsyncMock()),
            patch("src.bot.handlers.payments.get_voice_subscription_payment", AsyncMock(return_value=payment)),
            patch("src.bot.handlers.payments.mark_voice_subscription_payment_paid", AsyncMock()),
            patch("src.bot.handlers.payments.activate_voice_input_subscription", AsyncMock(return_value=access)),
        ):
            await handle_voice_subscription_callback(update, context)

        query.message.reply_text.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
