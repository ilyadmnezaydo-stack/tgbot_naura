import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.bot.handlers.forwarded import handle_pending_contact_description


class PendingContactFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_button_choice_before_consuming_context_text(self) -> None:
        update = SimpleNamespace(
            message=SimpleNamespace(
                text="случайное сообщение",
                reply_text=AsyncMock(),
            )
        )
        context = SimpleNamespace(
            user_data={
                "pending_contact": {
                    "username": "cbc0397",
                    "display_name": "я спать хочу",
                    "source": "manual_username",
                    "awaiting_context_choice": True,
                }
            }
        )

        with patch("src.bot.handlers.forwarded.get_optional_context_keyboard", return_value="keyboard"):
            consumed = await handle_pending_contact_description(update, context)

        self.assertTrue(consumed)
        self.assertIn("pending_contact", context.user_data)
        self.assertNotIn("draft_contact", context.user_data)
        update.message.reply_text.assert_awaited_once()
        self.assertEqual(update.message.reply_text.await_args.kwargs["parse_mode"], "HTML")
        self.assertEqual(update.message.reply_text.await_args.kwargs["reply_markup"], "keyboard")

    async def test_creates_draft_when_context_is_expected(self) -> None:
        update = SimpleNamespace(
            message=SimpleNamespace(
                text="коллега из маркетинга",
                reply_text=AsyncMock(),
            )
        )
        context = SimpleNamespace(
            user_data={
                "pending_contact": {
                    "username": "cbc0397",
                    "display_name": "я спать хочу",
                    "source": "manual_username",
                }
            }
        )
        enriched = SimpleNamespace(
            display_name="я спать хочу",
            description="коллега из маркетинга",
            tags=["#маркетинг"],
            birthday_day=None,
            birthday_month=None,
            birthday_year=None,
        )

        with patch("src.bot.handlers.forwarded.enrich_contact_data", AsyncMock(return_value=enriched)):
            consumed = await handle_pending_contact_description(update, context)

        self.assertTrue(consumed)
        self.assertNotIn("pending_contact", context.user_data)
        self.assertEqual(context.user_data["draft_contact"]["tags"], ["#маркетинг"])
        update.message.reply_text.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
