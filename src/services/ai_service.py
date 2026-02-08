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
    from types import SimpleNamespace

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


class ParsedContactEdit(BaseModel):
    """Structured output for contact edit parsing"""
    update_description: bool = Field(description="True если пользователь хочет изменить описание")
    new_description: Optional[str] = Field(default=None, description="Новое описание (если update_description=True)")
    update_tags: bool = Field(description="True если пользователь хочет изменить теги")
    new_tags: Optional[list[str]] = Field(default=None, description="Новые теги (если update_tags=True)")
    update_frequency: bool = Field(description="True если пользователь хочет изменить частоту")
    new_frequency_type: Optional[str] = Field(default=None, description="Новая частота")
    new_custom_days: Optional[int] = Field(default=None, description="Дни для custom частоты")
    new_reminder_date: Optional[str] = Field(default=None, description="Дата для one_time в формате YYYY-MM-DD")


class ParsedDate(BaseModel):
    """Structured output for date parsing"""
    date: Optional[str] = Field(description="Распознанная дата в формате YYYY-MM-DD")
    error: Optional[str] = Field(default=None, description="Сообщение об ошибке, если дату не удалось распознать")


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
1. **description** — описание контакта БЕЗ информации о частоте/дате напоминания. ВАЖНО: сохраняй все ссылки (URLs) в описании!
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
- "партнёр. через 10 дней" → description="партнёр", frequency_type="custom", custom_days=10
- "ментор https://getmentor.dev/profile/123" → description="ментор https://getmentor.dev/profile/123", frequency_type="biweekly" (ссылка сохранена!)""",
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

    async def parse_contact_edit(
        self,
        edit_request: str,
        current_description: str,
        current_tags: list[str],
        current_frequency: str,
    ) -> Optional[ParsedContactEdit]:
        """
        Parse edit request with context of current contact data.

        Args:
            edit_request: User's edit request like "раз в месяц" or "новое описание"
            current_description: Current contact description
            current_tags: Current contact tags
            current_frequency: Current reminder frequency

        Returns:
            ParsedContactEdit indicating which fields to update
        """
        if not edit_request or not edit_request.strip():
            return None

        today = date.today()
        tags_str = ", ".join(current_tags) if current_tags else "нет тегов"

        try:
            response = await self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": f"""Ты помощник для редактирования контакта. Сегодня: {today.isoformat()}.

Текущие данные контакта:
- Описание: "{current_description}"
- Теги: {tags_str}
- Частота: {current_frequency}

Пользователь хочет что-то изменить. Определи, ЧТО ИМЕННО он хочет изменить:

1. Если упоминает новое описание/информацию о человеке → update_description=True
2. Если упоминает теги (#тег) → update_tags=True
3. Если упоминает частоту/дату (раз в месяц, завтра, через 5 дней) → update_frequency=True

ВАЖНО: Меняй ТОЛЬКО то, что явно запрошено!
- "раз в месяц" → меняем только частоту, НЕ трогаем описание и теги
- "новый дизайнер" → меняем только описание, НЕ трогаем частоту
- "#друг #москва" → меняем только теги

ВАЖНО: Сохраняй все ссылки (URLs) в описании! Не удаляй их.

Частоты: daily, weekly, biweekly, monthly, custom, one_time
Для дат (сегодня, завтра, 15.01) используй one_time и reminder_date в формате YYYY-MM-DD.""",
                    },
                    {"role": "user", "content": edit_request},
                ],
                response_format=ParsedContactEdit,
            )

            parsed = response.choices[0].message.parsed
            if parsed and parsed.new_tags:
                # Ensure tags start with #
                parsed.new_tags = [
                    f"#{tag.lstrip('#')}" for tag in parsed.new_tags if tag
                ][:5]
            return parsed

        except Exception as e:
            logger.error(f"Error parsing contact edit: {e}")
            return None

    async def parse_date(self, text: str) -> Optional[date]:
        """
        Parse date from natural language using LLM.

        Supports various formats:
        - Relative: "завтра", "через неделю", "в следующую пятницу"
        - Absolute: "15 февраля", "15.02", "15/02/2025"
        - Natural: "в конце месяца", "на следующей неделе"

        Args:
            text: User input with date information

        Returns:
            date object or None if parsing failed
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
                        "content": f"""Ты парсер дат. Сегодня: {today.isoformat()} ({today.strftime('%A')}, {today.strftime('%d %B %Y')}).

Распознай дату из текста пользователя и верни её в формате YYYY-MM-DD.

Примеры:
- "завтра" → {(today + __import__('datetime').timedelta(days=1)).isoformat()}
- "послезавтра" → {(today + __import__('datetime').timedelta(days=2)).isoformat()}
- "через неделю" → {(today + __import__('datetime').timedelta(days=7)).isoformat()}
- "через 2 недели" → {(today + __import__('datetime').timedelta(days=14)).isoformat()}
- "через месяц" → дата через ~30 дней
- "15 февраля" → 2025-02-15 (или следующий год, если дата уже прошла)
- "в пятницу" → ближайшая пятница
- "в следующий понедельник" → понедельник следующей недели
- "в конце месяца" → последний день текущего месяца
- "1.03" или "01/03" → 2025-03-01

ВАЖНО:
- Дата должна быть в БУДУЩЕМ (после сегодня)
- Если дата неоднозначная, выбирай ближайшую будущую
- Если не можешь распознать, верни error с пояснением

Верни date=null и error="сообщение" если:
- Текст не содержит информации о дате
- Дата в прошлом и не может быть интерпретирована как будущая""",
                    },
                    {"role": "user", "content": text},
                ],
                response_format=ParsedDate,
            )

            parsed = response.choices[0].message.parsed
            if parsed and parsed.date:
                try:
                    return date.fromisoformat(parsed.date)
                except ValueError:
                    logger.warning(f"Invalid date format from AI: {parsed.date}")
                    return None
            return None

        except Exception as e:
            logger.error(f"Error parsing date: {e}")
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
        self, query: str, contacts: list["SimpleNamespace"]
    ) -> list["SimpleNamespace"]:
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
