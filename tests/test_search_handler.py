import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.bot.handlers.search import (
    _extract_query_words,
    _infer_query_tags,
    _find_context_matches,
    _find_tag_matches,
    _resolve_search_query,
    looks_like_search_query,
    perform_search,
)


class SearchHandlerTests(unittest.IsolatedAsyncioTestCase):
    def test_extract_query_words_keeps_russian_words(self) -> None:
        self.assertEqual(
            _extract_query_words("покажи контакты из маркетинга"),
            ["маркетинга"],
        )

    def test_infer_query_tags_from_natural_language(self) -> None:
        self.assertIn("#it", _infer_query_tags("кто у меня из айти"))

    def test_infer_query_tags_for_startup_roles(self) -> None:
        self.assertIn("#стартап", _infer_query_tags("кто у меня из стартаперов"))

    def test_looks_like_search_query_detects_common_voice_intent(self) -> None:
        self.assertTrue(looks_like_search_query("найди людей из маркетинга"))
        self.assertFalse(looks_like_search_query("привет как дела"))

    def test_tag_matches_are_ranked_before_context_matches(self) -> None:
        contacts = [
            SimpleNamespace(
                id=1,
                username="tagged",
                display_name="Теговый",
                description="знакомый",
                tags=["#маркетинг"],
            ),
            SimpleNamespace(
                id=2,
                username="contextual",
                display_name="Контекстный",
                description="человек из маркетинга",
                tags=["#другое"],
            ),
        ]

        tag_matches = _find_tag_matches("маркетинг", contacts)
        context_matches = _find_context_matches(
            "маркетинг",
            contacts,
            {contact.id for contact in tag_matches},
        )

        self.assertEqual([contact.username for contact in tag_matches], ["tagged"])
        self.assertEqual([contact.username for contact in context_matches], ["contextual"])

    def test_resolve_search_query_uses_voice_override(self) -> None:
        update = SimpleNamespace(message=SimpleNamespace(text=None))
        context = SimpleNamespace(user_data={"_input_text_override": "запрос из гс"})

        self.assertEqual(_resolve_search_query(update, context, None), "запрос из гс")

    async def test_perform_search_uses_voice_override_and_preserves_order(self) -> None:
        contacts = [
            SimpleNamespace(
                id=1,
                username="tagged",
                display_name="Теговый",
                description="знакомый",
                tags=["#маркетинг"],
            ),
            SimpleNamespace(
                id=2,
                username="contextual",
                display_name="Контекстный",
                description="человек из маркетинга",
                tags=[],
            ),
        ]
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            message=SimpleNamespace(
                text=None,
                reply_text=AsyncMock(),
                chat=SimpleNamespace(send_action=AsyncMock()),
            ),
        )
        context = SimpleNamespace(user_data={"_input_text_override": "маркетинг"})
        repo = SimpleNamespace(get_all_for_user=AsyncMock(return_value=contacts))
        ai_service = SimpleNamespace(semantic_search=AsyncMock(return_value=[]))

        with (
            patch("src.bot.handlers.search.get_supabase", AsyncMock(return_value=object())),
            patch("src.bot.handlers.search.ContactRepository", return_value=repo),
            patch("src.bot.handlers.search.AIService", return_value=ai_service),
            patch("src.bot.handlers.search.send_contact_card", AsyncMock()) as send_contact_card,
        ):
            await perform_search(update, context, None)

        ai_service.semantic_search.assert_not_awaited()
        sent_contacts = [call.args[1].username for call in send_contact_card.await_args_list]
        self.assertEqual(sent_contacts, ["tagged", "contextual"])


if __name__ == "__main__":
    unittest.main()
