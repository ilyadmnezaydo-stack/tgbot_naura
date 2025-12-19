"""
AI Service - OpenAI integration for smart features.
Used for:
1. Parsing contact input (description, tags, frequency)
2. Tag extraction from contact descriptions
3. Semantic search across contacts
"""
import json
import logging
from datetime import date
from typing import TYPE_CHECKING, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from src.config import settings

if TYPE_CHECKING:
    from src.db.models import Contact

logger = logging.getLogger(__name__)


class ParsedContactInput(BaseModel):
    """Structured output for contact parsing"""
    description: str = Field(description="Описание контакта без информации о частоте напоминаний")
    tags: list[str] = Field(description="Теги в формате #tag, максимум 5")
    frequency_type: str = Field(
        description="Тип частоты: daily, weekly, biweekly, monthly, custom, one_time. По умолчанию biweekly"
    )
    custom_days: Optional[int] = Field(
        default=None,
        description="Количество дней для custom частоты (например, 'через 10 дней' = 10)"
    )
    reminder_date: Optional[str] = Field(
        default=None,
        description="Дата напоминания в формате YYYY-MM-DD для one_time или относительных дат (сегодня, завтра)"
    )


class AIService:
    """AI service for contact parsing, tag extraction, and semantic search"""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.OPENAI_MODEL

    async def parse_contact_input(self, text: str) -> Optional[ParsedContactInput]:
        """
        Parse contact input using LLM with structured output.

        Extracts:
        - description (without frequency info)
        - tags
        - frequency type and custom days
        - reminder date for one-time reminders

        Args:
            text: Raw input like "коллега из IT, Москва. напомни завтра"

        Returns:
            ParsedContactInput or None if parsing failed
        """
        if not text or not text.strip():
            return None

        today = date.today()

        try:
            response = await self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": f"""Ты парсер контактной информации. Сегодня: {today.isoformat()} ({today.strftime('%A')}).

Извлеки из текста:
1. **description** — описание контакта БЕЗ информации о частоте/дате напоминания
2. **tags** — теги на основе описания (профессия, сфера, отношения, локация). Формат: #тег. Максимум 5.
3. **frequency_type** — частота напоминаний:
   - "daily" — каждый день, ежедневно
   - "weekly" — раз в неделю, еженедельно
   - "biweekly" — раз в 2 недели (по умолчанию если не указано)
   - "monthly" — раз в месяц
   - "custom" — через X дней, каждые X дней
   - "one_time" — разово, один раз, конкретная дата, "сегодня", "завтра"
4. **custom_days** — число дней для "custom" (например, "через 5 дней" = 5)
5. **reminder_date** — дата в формате YYYY-MM-DD для:
   - "сегодня" = {today.isoformat()}
   - "завтра" = {(today + __import__('datetime').timedelta(days=1)).isoformat()}
   - "послезавтра" = {(today + __import__('datetime').timedelta(days=2)).isoformat()}
   - конкретные даты (15.01, 15 января, etc.)
   - дни недели (понедельник = ближайший понедельник)

Примеры:
- "коллега из маркетинга" → description="коллега из маркетинга", frequency_type="biweekly"
- "друг. раз в месяц" → description="друг", frequency_type="monthly"
- "инвестор. напомни завтра" → description="инвестор", frequency_type="one_time", reminder_date=завтрашняя дата
- "партнёр. через 10 дней" → description="партнёр", frequency_type="custom", custom_days=10""",
                    },
                    {"role": "user", "content": text},
                ],
                response_format=ParsedContactInput,
            )

            parsed = response.choices[0].message.parsed
            if parsed:
                # Ensure tags start with #
                parsed.tags = [
                    f"#{tag.lstrip('#')}" for tag in parsed.tags if tag
                ][:5]
                return parsed
            return None

        except Exception as e:
            logger.error(f"Error parsing contact input: {e}")
            return None

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
