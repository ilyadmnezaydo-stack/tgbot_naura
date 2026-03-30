"""
AI service for local OpenAI-compatible models.

Used for:
1. Parsing contact input (description, tags, frequency)
2. Tag extraction from contact descriptions
3. Semantic search across contacts
"""
import json
import logging
import re
import asyncio
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, Optional, TypeVar

from pydantic import BaseModel, Field, ValidationError
import requests

from src.config import settings

if TYPE_CHECKING:
    from types import SimpleNamespace

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


class ParsedContactInput(BaseModel):
    """Structured output for contact parsing."""

    description: str = Field(
        description="Описание контакта без информации о частоте напоминаний"
    )
    tags: list[str] = Field(description="Теги в формате #tag, максимум 5")
    frequency_type: str = Field(
        description=(
            "Тип частоты: daily, weekly, biweekly, monthly, custom, one_time. "
            "По умолчанию biweekly"
        )
    )
    custom_days: Optional[int] = Field(
        default=None,
        description="Количество дней для custom частоты",
    )
    reminder_date: Optional[str] = Field(
        default=None,
        description="Дата напоминания в формате YYYY-MM-DD",
    )


class ParsedContactEdit(BaseModel):
    """Structured output for contact edit parsing."""

    update_description: bool = Field(
        description="True если пользователь хочет изменить описание"
    )
    new_description: Optional[str] = Field(
        default=None,
        description="Новое описание",
    )
    update_tags: bool = Field(description="True если пользователь хочет изменить теги")
    new_tags: Optional[list[str]] = Field(default=None, description="Новые теги")
    update_frequency: bool = Field(
        description="True если пользователь хочет изменить частоту"
    )
    new_frequency_type: Optional[str] = Field(
        default=None,
        description="Новая частота",
    )
    new_custom_days: Optional[int] = Field(
        default=None,
        description="Дни для custom частоты",
    )
    new_reminder_date: Optional[str] = Field(
        default=None,
        description="Дата для one_time в формате YYYY-MM-DD",
    )


class ParsedDate(BaseModel):
    """Structured output for date parsing."""

    date: Optional[str] = Field(description="Распознанная дата в формате YYYY-MM-DD")
    error: Optional[str] = Field(
        default=None,
        description="Сообщение об ошибке, если дату не удалось распознать",
    )


class SupportTriage(BaseModel):
    """Structured output for the first support response."""

    is_complex: bool = Field(
        description="True если вопрос лучше передать человеку"
    )
    answer: Optional[str] = Field(
        default=None,
        description="Короткий ответ пользователю, если вопрос простой",
    )
    category: str = Field(
        description="Категория вопроса: howto, bug, payment, reminders, search, contacts, notes, other"
    )
    reason: Optional[str] = Field(
        default=None,
        description="Почему вопрос стоит передать человеку",
    )


class InterpretedSearchRequest(BaseModel):
    """Structured output for deciding whether a message should trigger contact search."""

    is_contact_search: bool = Field(
        description="True если пользователь хочет найти или показать контакты"
    )
    search_query: Optional[str] = Field(
        default=None,
        description="Короткий нормализованный запрос для поиска по контактам",
    )


class SemanticSearchSelection(BaseModel):
    """Structured output for semantic contact search."""

    usernames: list[str] = Field(
        default_factory=list,
        description="Список username, отсортированных по релевантности",
    )


class AIService:
    """AI service for contact parsing, tag extraction, and semantic search."""

    _PLACEHOLDER_VALUES = {"unknown", "неопределено", "undefined", "none", "null", "n/a"}
    _PLACEHOLDER_TAGS = {"#unknown", "#неопределено", "#undefined", "#other", "#misc", "#tag"}

    def __init__(self):
        self.base_url = settings.LLM_BASE_URL.rstrip("/")
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL

    @staticmethod
    def _normalize_tag(tag: str) -> str:
        clean_tag = tag.lstrip("#").strip()
        return f"#{clean_tag}" if clean_tag else ""

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
        return text

    @classmethod
    def _extract_json_payload(cls, text: str) -> str:
        cleaned = cls._strip_markdown_fences(text)

        for opener, closer in (("{", "}"), ("[", "]")):
            start = cleaned.find(opener)
            end = cleaned.rfind(closer)
            if start != -1 and end != -1 and end > start:
                return cleaned[start : end + 1]

        return cleaned

    @staticmethod
    def _message_to_text(message: Any) -> str:
        if isinstance(message, dict):
            content = message.get("content", "")
            if isinstance(content, str):
                return content.strip()

        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content.strip()

        parts: list[str] = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    text_value = item.get("text", "")
                    if isinstance(text_value, dict):
                        value = text_value.get("value") or text_value.get("content") or ""
                        if value:
                            parts.append(str(value))
                    elif text_value:
                        parts.append(str(text_value))
                    continue

                text_value = getattr(item, "text", "")
                if isinstance(text_value, str) and text_value:
                    parts.append(text_value)
                    continue

                value = getattr(text_value, "value", "")
                if value:
                    parts.append(str(value))

        return "\n".join(parts).strip()

    @staticmethod
    def _compact_text(value: str | None, limit: int = 280) -> str:
        """Keep prompt payload compact while preserving the key meaning."""
        if not value:
            return ""
        compact = " ".join(value.split()).strip()
        if len(compact) <= limit:
            return compact
        return compact[: limit - 1].rstrip() + "…"

    @classmethod
    def _is_low_signal_text(cls, value: str | None) -> bool:
        """Detect placeholder-like model output that should not overwrite user data."""
        compact = " ".join((value or "").split()).strip()
        if not compact:
            return True

        if compact.lower() in cls._PLACEHOLDER_VALUES:
            return True

        visible_chars = [char for char in compact if not char.isspace()]
        if not visible_chars:
            return True

        placeholder_chars = sum(1 for char in visible_chars if char in {"?", "�"})
        return placeholder_chars / len(visible_chars) >= 0.35

    @classmethod
    def _sanitize_tags(cls, tags: list[str] | None) -> list[str]:
        """Drop duplicate or placeholder tags returned by the model."""
        sanitized: list[str] = []
        seen: set[str] = set()

        for raw_tag in tags or []:
            normalized = cls._normalize_tag(raw_tag)
            if not normalized or normalized in cls._PLACEHOLDER_TAGS:
                continue

            if cls._is_low_signal_text(normalized.lstrip("#")):
                continue

            if normalized in seen:
                continue

            seen.add(normalized)
            sanitized.append(normalized)
            if len(sanitized) >= 5:
                break

        return sanitized

    async def _complete(self, system_prompt: str, user_prompt: str) -> str:
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                headers = {"Content-Type": "application/json"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"

                response = await asyncio.to_thread(
                    requests.post,
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json={
                        "model": self.model,
                        "temperature": 0,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                    timeout=120,
                )

                if response.status_code == 503 and attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue

                response.raise_for_status()
                data = response.json()
                message = data["choices"][0]["message"]
                return self._message_to_text(message)
            except Exception as e:
                last_error = e
                if getattr(e, "response", None) is not None and getattr(e.response, "status_code", None) == 503 and attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue

                if getattr(e, "status_code", None) != 503 or attempt == 2:
                    raise

                # Ollama can return 503 while the model is still loading into memory.
                await asyncio.sleep(2 * (attempt + 1))

        raise last_error if last_error else RuntimeError("Completion failed")

    async def _complete_model(
        self,
        system_prompt: str,
        user_prompt: str,
        model_cls: type[ModelT],
    ) -> Optional[ModelT]:
        try:
            text = await self._complete(system_prompt, user_prompt)
            payload = self._extract_json_payload(text)
            data = json.loads(payload)
            return model_cls.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(f"Failed to parse model response for {model_cls.__name__}: {e}")
            return None
        except Exception as e:
            logger.error(f"Completion failed for {model_cls.__name__}: {e}")
            return None

    async def _complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Optional[Any]:
        try:
            text = await self._complete(system_prompt, user_prompt)
            payload = self._extract_json_payload(text)
            return json.loads(payload)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            return None
        except Exception as e:
            logger.error(f"Completion failed: {e}")
            return None

    async def parse_contact_input(self, text: str) -> Optional[ParsedContactInput]:
        """
        Parse contact input using the local LLM and return structured data.
        """
        if not text or not text.strip():
            return None

        today = date.today()
        tomorrow = today + timedelta(days=1)
        day_after_tomorrow = today + timedelta(days=2)

        system_prompt = f"""Ты парсер контактной информации.
Сегодня: {today.isoformat()}.

Извлеки из текста JSON-объект строго такого вида:
{{
  "description": "строка",
  "tags": ["#tag1", "#tag2"],
  "frequency_type": "daily|weekly|biweekly|monthly|custom|one_time",
  "custom_days": null,
  "reminder_date": null
}}

Правила:
- description: описание контакта без информации о частоте/дате напоминания
- обязательно сохраняй все ссылки (URLs) в description
- tags: максимум 5 тегов, формат #tag
- если частота не указана, используй "biweekly"
- custom_days: число дней только для custom
- reminder_date: YYYY-MM-DD только для one_time и относительных дат
- "сегодня" = {today.isoformat()}
- "завтра" = {tomorrow.isoformat()}
- "послезавтра" = {day_after_tomorrow.isoformat()}
- если какой-то части нет, ставь null или []

Верни только JSON без пояснений."""

        parsed = await self._complete_model(system_prompt, text, ParsedContactInput)
        if not parsed:
            return None

        fallback_description = " ".join(text.split()).strip()
        if self._is_low_signal_text(parsed.description):
            parsed.description = fallback_description
        else:
            parsed.description = " ".join(parsed.description.split()).strip()

        parsed.tags = self._sanitize_tags(parsed.tags)
        return parsed

    async def parse_contact_edit(
        self,
        edit_request: str,
        current_description: str,
        current_tags: list[str],
        current_frequency: str,
    ) -> Optional[ParsedContactEdit]:
        """
        Parse edit request with current contact data as context.
        """
        if not edit_request or not edit_request.strip():
            return None

        today = date.today()
        tags_str = ", ".join(current_tags) if current_tags else "нет тегов"

        system_prompt = f"""Ты помощник для редактирования контакта.
Сегодня: {today.isoformat()}.

Текущие данные:
- description: {current_description!r}
- tags: {tags_str}
- frequency: {current_frequency}

Верни строго JSON-объект:
{{
  "update_description": true,
  "new_description": null,
  "update_tags": false,
  "new_tags": null,
  "update_frequency": false,
  "new_frequency_type": null,
  "new_custom_days": null,
  "new_reminder_date": null
}}

Правила:
- меняй только то, что пользователь явно попросил
- если меняется описание, сохрани URLs
- new_tags: список тегов в формате #tag
- частоты: daily, weekly, biweekly, monthly, custom, one_time
- даты возвращай в формате YYYY-MM-DD
- если поле не меняется, ставь false/null

Верни только JSON без пояснений."""

        parsed = await self._complete_model(system_prompt, edit_request, ParsedContactEdit)
        if not parsed:
            return None

        if parsed.new_tags:
            parsed.new_tags = [
                normalized
                for normalized in (self._normalize_tag(tag) for tag in parsed.new_tags)
                if normalized
            ][:5]

        return parsed

    async def parse_date(self, text: str) -> Optional[date]:
        """
        Parse a natural-language date into a date object.
        """
        if not text or not text.strip():
            return None

        today = date.today()
        system_prompt = f"""Ты парсер дат.
Сегодня: {today.isoformat()}.

Верни строго JSON-объект:
{{
  "date": "YYYY-MM-DD или null",
  "error": "сообщение или null"
}}

Правила:
- распознавай относительные даты: сегодня, завтра, послезавтра, через неделю
- распознавай абсолютные даты: 15.02, 15 февраля, 2026-02-15
- распознавай естественные формулировки: в пятницу, в конце месяца
- date должна быть в будущем или сегодня
- если распознать не удалось, верни date=null и заполни error

Верни только JSON без пояснений."""

        parsed = await self._complete_model(system_prompt, text, ParsedDate)
        if not parsed or not parsed.date:
            return None

        try:
            return date.fromisoformat(parsed.date)
        except ValueError:
            logger.warning(f"Invalid date format from model: {parsed.date}")
            return None

    async def extract_tags(self, description: str) -> list[str]:
        """
        Extract relevant tags from a contact description.
        """
        if not description or not description.strip():
            return []

        system_prompt = """Ты извлекаешь теги из описания контакта.

Верни только JSON-массив строк, например:
["#IT", "#друг", "#Москва"]

Правила:
- максимум 5 тегов
- короткие и понятные
- формат всегда начинается с #
- не добавляй пояснения и markdown"""

        data = await self._complete_json(system_prompt, description)
        if not isinstance(data, list):
            return []

        return self._sanitize_tags([tag for tag in data if isinstance(tag, str)])

    async def interpret_contact_search_request(self, text: str) -> Optional[str]:
        """
        Decide whether a free-form message is a contact search request and normalize it.
        Useful after speech-to-text, when voice phrasing is conversational.
        """
        if not text or not text.strip():
            return None

        system_prompt = """Ты понимаешь запросы пользователя к личному CRM по контактам.

Верни строго JSON:
{
  "is_contact_search": true,
  "search_query": "краткий поисковый запрос или null"
}

Правила:
- is_contact_search=true, если пользователь хочет найти, показать, перечислить, отфильтровать или спросить, есть ли контакты с нужными признаками
- если это не поиск контактов, верни is_contact_search=false и search_query=null
- search_query должен быть коротким, но сохранить все важные фильтры: роль, сфера, город, интерес, имя, компания и т.д.
- не отвечай на вопрос сам, не объясняй логику, только классифицируй и нормализуй запрос
- если формулировка уже хорошая, можно вернуть её почти без изменений

Верни только JSON без пояснений."""

        parsed = await self._complete_model(system_prompt, text, InterpretedSearchRequest)
        if not parsed or not parsed.is_contact_search:
            return None

        normalized_query = " ".join((parsed.search_query or "").split()).strip()
        if self._is_low_signal_text(normalized_query):
            normalized_query = " ".join(text.split()).strip()
        return normalized_query or None

    async def semantic_search(
        self,
        query: str,
        contacts: list["SimpleNamespace"],
        contact_notes: Optional[dict[str, list[str]]] = None,
    ) -> list["SimpleNamespace"]:
        """
        Use the local LLM to find contacts matching a semantic query.
        """
        if not contacts or not query or not query.strip():
            return []

        contacts_info = [
            {
                "username": contact.username,
                "display_name": getattr(contact, "display_name", None) or "",
                "description": self._compact_text(contact.description or "", limit=320),
                "tags": contact.tags or [],
                "notes": [
                    self._compact_text(note, limit=180)
                    for note in (contact_notes or {}).get(str(getattr(contact, "id", "")), [])[:3]
                    if note
                ],
            }
            for contact in contacts
        ]

        system_prompt = """Ты помогаешь искать контакты в личном CRM.

Пользователь может спрашивать как прямо, так и косвенно:
- «кто из бизнеса в Москве»
- «покажи людей из стартапов»
- «есть ли у меня кто-то по инвестициям»

Для каждого контакта доступны поля:
- username
- display_name
- description
- tags
- notes

Правила:
- ищи по совокупности признаков, а не только по буквальному совпадению слов
- notes тоже важны: в них может быть свежий контекст по человеку
- можно делать осторожные выводы по близким понятиям:
  founder / cofounder / стартап / предприниматель / owner / CEO / инвестиции / b2b / SaaS -> могут быть связаны с бизнесом
  Москва / Moscow / мск -> это Москва
- не выдумывай факты, если в данных нет разумной опоры
- возвращай только действительно подходящие контакты
- сортируй usernames по убыванию релевантности

Верни строго JSON:
{
  "usernames": ["ivan", "anna"]
}

Если подходящих нет, верни {"usernames": []}. Без пояснений."""

        user_prompt = (
            f"Запрос пользователя: {query}\n\n"
            f"Контакты:\n{json.dumps(contacts_info, ensure_ascii=False, indent=2)}"
        )
        parsed = await self._complete_model(system_prompt, user_prompt, SemanticSearchSelection)
        if not parsed:
            return []

        matching_usernames = [username.lower() for username in parsed.usernames if isinstance(username, str)]
        return [
            contact
            for contact in contacts
            if contact.username.lower() in matching_usernames
        ]

    async def triage_support_question(self, question: str) -> Optional[SupportTriage]:
        """Answer simple support questions or mark them for human escalation."""
        if not question or not question.strip():
            return None

        system_prompt = """Ты первая линия поддержки Telegram-бота для личного CRM по контактам.

Бот умеет:
- добавлять контакт через `@username описание`
- добавлять контакт из пересланного сообщения
- хранить описание, теги и частоту напоминаний
- показывать список контактов и карточки
- искать контакты по смыслу, тегам и имени
- сохранять заметки после общения
- принимать поддержку через Telegram Stars
- показывать дашборд только владельцу бота

Твоя задача: понять, можно ли уверенно ответить сразу.

Считай вопрос сложным, если:
- пользователь сообщает о баге, сбое, потере данных или странном поведении
- нужен доступ администратора или ручная проверка
- вопрос про оплату, возврат, ограничения Telegram или приватность
- пользователь явно просит человека
- ты не уверен в ответе

Верни строго JSON:
{
  "is_complex": false,
  "answer": "краткий ответ пользователю или null",
  "category": "howto|bug|payment|reminders|search|contacts|notes|other",
  "reason": "пояснение или null"
}

Правила:
- если вопрос простой, answer должен быть полезным, коротким и понятным, без воды
- если вопрос сложный, answer = null
- не придумывай несуществующие функции
- не используй markdown-таблицы и лишние вступления

Верни только JSON без пояснений."""

        return await self._complete_model(system_prompt, question, SupportTriage)
