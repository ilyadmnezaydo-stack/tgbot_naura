import unittest
from unittest.mock import AsyncMock, patch

from src.services.ai_service import AIService, InterpretedSearchRequest, ParsedContactInput


class AIServiceGuardrailTests(unittest.IsolatedAsyncioTestCase):
    async def test_parse_contact_input_keeps_original_text_when_model_returns_placeholders(self) -> None:
        service = AIService()
        model_result = ParsedContactInput(
            description="???? ?? ?????",
            tags=["#неопределено", "#стартап"],
            frequency_type="biweekly",
        )

        with patch.object(AIService, "_complete_model", AsyncMock(return_value=model_result)):
            parsed = await service.parse_contact_input("основатель стартапа из москвы")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.description, "основатель стартапа из москвы")
        self.assertEqual(parsed.tags, ["#стартап"])

    async def test_extract_tags_drops_placeholder_tags(self) -> None:
        service = AIService()

        with patch.object(AIService, "_complete_json", AsyncMock(return_value=["#неопределено", "#бизнес"])):
            tags = await service.extract_tags("занимается бизнесом")

        self.assertEqual(tags, ["#бизнес"])

    async def test_interpret_contact_search_request_falls_back_to_original_text(self) -> None:
        service = AIService()
        model_result = InterpretedSearchRequest(
            is_contact_search=True,
            search_query="?????? ???",
        )

        with patch.object(AIService, "_complete_model", AsyncMock(return_value=model_result)):
            query = await service.interpret_contact_search_request("а у меня кто-нибудь из бизнеса в москве есть")

        self.assertEqual(query, "а у меня кто-нибудь из бизнеса в москве есть")


if __name__ == "__main__":
    unittest.main()
