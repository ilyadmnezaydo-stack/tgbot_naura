"""
AI Service - OpenAI integration for smart features.
Used for:
1. Tag extraction from contact descriptions
2. Semantic search across contacts
"""
import json
import logging
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from src.config import settings

if TYPE_CHECKING:
    from src.db.models import Contact

logger = logging.getLogger(__name__)


class AIService:
    """AI service for tag extraction and semantic search"""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.OPENAI_MODEL

    async def extract_tags(self, description: str) -> list[str]:
        """
        Extract relevant tags from contact description.

        Examples:
            "работает в маркетинге" -> ["#marketing", "#работа"]
            "друг из универа" -> ["#друг", "#универ"]
            "инвестор, интересуется AI" -> ["#инвестор", "#AI", "#бизнес"]

        Returns:
            List of tags starting with #
        """
        if not description or not description.strip():
            return []

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                reasoning_effort="minimal",
                messages=[
                    {
                        "role": "system",
                        "content": """Ты помогаешь извлекать теги из описания контактов.
Верни JSON массив тегов на основе описания.

Правила:
- Теги на русском или английском (если профессиональный термин)
- Начинаются с #
- Краткие (1-2 слова)
- Отражают: профессию, отношения, интересы, локацию, сферу деятельности
- Максимум 5 тегов
- Используй популярные/понятные теги

Примеры:
"коллега из IT отдела, любит футбол" -> ["#IT", "#коллега", "#футбол"]
"подруга, живёт в Москве, дизайнер" -> ["#дизайн", "#друг", "#Москва"]
"инвестор в стартапы, знакомый с конференции" -> ["#инвестор", "#стартапы", "#нетворкинг"]

Верни только JSON массив, без объяснений.""",
                    },
                    {"role": "user", "content": description},
                ],
                max_completion_tokens=100,
            )

            tags_text = response.choices[0].message.content.strip()

            # Parse JSON response
            tags = json.loads(tags_text)

            # Ensure all tags start with # and are valid
            result = []
            for tag in tags:
                if isinstance(tag, str) and tag:
                    clean_tag = tag.lstrip("#").strip()
                    if clean_tag:
                        result.append(f"#{clean_tag}")

            return result[:5]  # Max 5 tags

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse AI response as JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Error extracting tags: {e}")
            return []

    async def semantic_search(
        self, query: str, contacts: list["Contact"]
    ) -> list["Contact"]:
        """
        Use AI to find contacts matching the semantic query.

        Args:
            query: User's search query in natural language
            contacts: List of user's contacts to search through

        Returns:
            List of matching contacts
        """
        if not contacts:
            return []

        # Prepare contacts info for AI
        contacts_info = []
        for c in contacts:
            info = {
                "username": c.username,
                "description": c.description or "",
                "tags": c.tags or [],
            }
            contacts_info.append(info)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                reasoning_effort="minimal",
                messages=[
                    {
                        "role": "system",
                        "content": """Ты помогаешь искать контакты по запросу пользователя.

Проанализируй список контактов и верни JSON массив username тех, кто соответствует запросу.

Учитывай:
- Описание контакта
- Теги
- Семантическое сходство (например, "IT" включает "программист", "разработчик", "developer")
- Синонимы и связанные понятия

Правила:
- Верни только тех, кто реально подходит под запрос
- Если запрос широкий, можно вернуть несколько контактов
- Если никто не подходит, верни пустой массив []

Формат ответа: JSON массив username, например: ["ivan", "anna"]""",
                    },
                    {
                        "role": "user",
                        "content": f"Запрос: {query}\n\nКонтакты:\n{json.dumps(contacts_info, ensure_ascii=False, indent=2)}",
                    },
                ],
                max_completion_tokens=200,
            )

            result_text = response.choices[0].message.content.strip()

            # Parse JSON response
            matching_usernames = json.loads(result_text)

            # Filter contacts by matching usernames (case-insensitive)
            matching_usernames_lower = [u.lower() for u in matching_usernames]
            return [c for c in contacts if c.username.lower() in matching_usernames_lower]

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse AI search response as JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Error in semantic search: {e}")
            return []
