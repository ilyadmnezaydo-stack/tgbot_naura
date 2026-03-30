import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.bot.app import route_text_input, route_voice_message


class VoiceSearchRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_voice_override_can_trigger_search_without_explicit_search_mode(self) -> None:
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(user_data={"_input_text_override": "найди людей из маркетинга"})

        with (
            patch("src.bot.app.handle_navigation_button", AsyncMock(return_value=False)),
            patch("src.bot.app.record_interaction", AsyncMock()),
            patch("src.bot.app.handle_cloudpayments_amount_input", AsyncMock(return_value=False)),
            patch("src.bot.app.handle_donation_amount_input", AsyncMock(return_value=False)),
            patch("src.bot.app.handle_pending_contact_description", AsyncMock(return_value=False)),
            patch("src.bot.app.handle_contact_note_input", AsyncMock(return_value=False)),
            patch("src.bot.app.handle_support_admin_reply_input", AsyncMock(return_value=False)),
            patch("src.bot.app.handle_support_question_input", AsyncMock(return_value=False)),
            patch("src.bot.app.handle_support_followup_input", AsyncMock(return_value=False)),
            patch("src.bot.app.handle_contact_lookup_from_list", AsyncMock(return_value=False)),
            patch("src.bot.app.check_and_offer_username_contact", AsyncMock(return_value=False)),
            patch("src.bot.app.perform_search", AsyncMock()) as perform_search,
        ):
            await route_text_input(update, context, "найди людей из маркетинга", allow_navigation_buttons=False)

        perform_search.assert_awaited_once_with(update, context, "найди людей из маркетинга")

    async def test_voice_override_can_trigger_search_via_ai_interpretation(self) -> None:
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(user_data={"_input_text_override": "а у меня кто-нибудь из бизнеса в москве есть"})
        ai_service = SimpleNamespace(
            interpret_contact_search_request=AsyncMock(return_value="бизнес в москве"),
        )

        with (
            patch("src.bot.app.handle_navigation_button", AsyncMock(return_value=False)),
            patch("src.bot.app.record_interaction", AsyncMock()),
            patch("src.bot.app.handle_cloudpayments_amount_input", AsyncMock(return_value=False)),
            patch("src.bot.app.handle_donation_amount_input", AsyncMock(return_value=False)),
            patch("src.bot.app.handle_pending_contact_description", AsyncMock(return_value=False)),
            patch("src.bot.app.handle_contact_note_input", AsyncMock(return_value=False)),
            patch("src.bot.app.handle_support_admin_reply_input", AsyncMock(return_value=False)),
            patch("src.bot.app.handle_support_question_input", AsyncMock(return_value=False)),
            patch("src.bot.app.handle_support_followup_input", AsyncMock(return_value=False)),
            patch("src.bot.app.handle_contact_lookup_from_list", AsyncMock(return_value=False)),
            patch("src.bot.app.check_and_offer_username_contact", AsyncMock(return_value=False)),
            patch("src.bot.app.AIService", return_value=ai_service),
            patch("src.bot.app.perform_search", AsyncMock()) as perform_search,
        ):
            await route_text_input(update, context, "а у меня кто-нибудь из бизнеса в москве есть", allow_navigation_buttons=False)

        ai_service.interpret_contact_search_request.assert_awaited_once_with("а у меня кто-нибудь из бизнеса в москве есть")
        perform_search.assert_awaited_once_with(update, context, "бизнес в москве")

    async def test_voice_search_mode_shows_recognized_query_before_routing(self) -> None:
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(user_data={"awaiting_search": True}, bot=object())
        transcription = SimpleNamespace(text="маркетинг", source="voice")
        stt_service = SimpleNamespace(transcribe_message=AsyncMock(return_value=transcription))
        access = SimpleNamespace(
            has_access=True,
            access_type="trial_active",
            trial_expires_at=None,
            subscription_expires_at=None,
        )

        with (
            patch("src.bot.app.ensure_voice_input_access", AsyncMock(return_value=access)),
            patch("src.bot.app.SpeechToTextService", return_value=stt_service),
            patch("src.bot.app.route_text_input", AsyncMock()) as route_text_input_mock,
        ):
            await route_voice_message(update, context)

        update.message.reply_text.assert_awaited_once()
        self.assertIn("Распознал запрос", update.message.reply_text.await_args.args[0])
        route_text_input_mock.assert_awaited_once_with(
            update,
            context,
            "маркетинг",
            allow_navigation_buttons=False,
        )

    async def test_voice_contact_note_mode_shows_recognized_note_before_routing(self) -> None:
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(
            user_data={"awaiting_contact_note": {"contact_id": "abc", "username": "ivan"}},
            bot=object(),
        )
        transcription = SimpleNamespace(text="обсудили демо на вторник", source="voice")
        stt_service = SimpleNamespace(transcribe_message=AsyncMock(return_value=transcription))
        access = SimpleNamespace(
            has_access=True,
            access_type="trial_active",
            trial_expires_at=None,
            subscription_expires_at=None,
        )

        with (
            patch("src.bot.app.ensure_voice_input_access", AsyncMock(return_value=access)),
            patch("src.bot.app.SpeechToTextService", return_value=stt_service),
            patch("src.bot.app.route_text_input", AsyncMock()) as route_text_input_mock,
        ):
            await route_voice_message(update, context)

        update.message.reply_text.assert_awaited_once()
        self.assertIn("Распознал заметку", update.message.reply_text.await_args.args[0])
        route_text_input_mock.assert_awaited_once_with(
            update,
            context,
            "обсудили демо на вторник",
            allow_navigation_buttons=False,
        )

    async def test_voice_message_is_blocked_when_trial_has_expired(self) -> None:
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(user_data={}, bot=object())
        access = SimpleNamespace(
            has_access=False,
            access_type="expired",
            trial_expires_at=None,
            subscription_expires_at=None,
        )

        with (
            patch("src.bot.app.ensure_voice_input_access", AsyncMock(return_value=access)),
            patch("src.bot.app.SpeechToTextService") as stt_cls,
        ):
            await route_voice_message(update, context)

        stt_cls.assert_not_called()
        update.message.reply_text.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
