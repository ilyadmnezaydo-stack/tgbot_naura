"""
Conservative enrichment helpers for newly added contacts.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

from src.services.ai_service import AIService
from src.services.telegram_username_service import (
    UsernameValidationResult,
    UsernameValidationUnavailable,
    validate_public_username,
)

logger = logging.getLogger(__name__)

_HASHTAG_RE = re.compile(r"#([\wа-яА-ЯёЁ-]+)", flags=re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")
_CLEAN_NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё' -]{0,78}$")

_NAME_PATTERNS = (
    re.compile(
        r"(?i)\b(?:зовут|имя|name is|named)\s+([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё' -]{0,60})"
    ),
    re.compile(r"^\s*([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё' -]{1,60})\s*[,—:-]"),
    re.compile(
        r"^\s*([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё' -]{1,60})\s+"
        r"(?:из|с|по|работает|учится|дизайнер|разработчик|коллега|друг|подруга|"
        r"знакомый|знакомая|ментор|фаундер|основатель|маркетолог|продуктолог|pm|devrel)\b"
    ),
)

_KEYWORD_TAGS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(коллег|работ|команд|офис|проект)\w*", re.IGNORECASE), "#работа"),
    (re.compile(r"\b(друг|подруг|приятел|знаком)\w*", re.IGNORECASE), "#друзья"),
    (re.compile(r"\b(семь|мама|папа|брат|сестр|родн)\w*", re.IGNORECASE), "#семья"),
    (re.compile(r"\b(клиент|заказчик)\w*", re.IGNORECASE), "#клиенты"),
    (re.compile(r"\b(бизнес|предприним|owner|ceo|coo|cfo|владелец|директор)\w*", re.IGNORECASE), "#бизнес"),
    (re.compile(r"\b(москв|moscow|мск)\w*", re.IGNORECASE), "#москва"),
    (
        re.compile(
            r"\b(стартап|startup|фаундер|founder|основател|entrepreneur)\w*",
            re.IGNORECASE,
        ),
        "#стартап",
    ),
    (re.compile(r"\b(партнер|партнёр|cofounder|co-founder)\w*", re.IGNORECASE), "#партнеры"),
    (re.compile(r"\b(it|айти|разработ|developer|backend|frontend|python|java|devops)\w*", re.IGNORECASE), "#it"),
    (re.compile(r"\b(дизайн|дизайнер|ux|ui|product design)\w*", re.IGNORECASE), "#дизайн"),
    (re.compile(r"\b(маркет|marketing|growth|smm)\w*", re.IGNORECASE), "#маркетинг"),
    (re.compile(r"\b(продукт|product manager|product)\w*", re.IGNORECASE), "#продукт"),
    (re.compile(r"\b(инвест|vc|venture)\w*", re.IGNORECASE), "#инвестиции"),
)

_MONTHS = {
    "января": 1,
    "январь": 1,
    "january": 1,
    "jan": 1,
    "февраля": 2,
    "февраль": 2,
    "february": 2,
    "feb": 2,
    "марта": 3,
    "март": 3,
    "march": 3,
    "mar": 3,
    "апреля": 4,
    "апрель": 4,
    "april": 4,
    "apr": 4,
    "мая": 5,
    "май": 5,
    "may": 5,
    "июня": 6,
    "июнь": 6,
    "june": 6,
    "jun": 6,
    "июля": 7,
    "июль": 7,
    "july": 7,
    "jul": 7,
    "августа": 8,
    "август": 8,
    "august": 8,
    "aug": 8,
    "сентября": 9,
    "сентябрь": 9,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "октября": 10,
    "октябрь": 10,
    "october": 10,
    "oct": 10,
    "ноября": 11,
    "ноябрь": 11,
    "november": 11,
    "nov": 11,
    "декабря": 12,
    "декабрь": 12,
    "december": 12,
    "dec": 12,
}
_MONTH_PATTERN = "|".join(sorted((re.escape(key) for key in _MONTHS), key=len, reverse=True))
_BIRTHDAY_CUE = r"(?:день\s*рожд(?:ения|енье)|\bдр\b|д\.р\.|родил(?:ся|ась)|birthday|born)"
_NUMERIC_BIRTHDAY_RE = re.compile(
    rf"(?i){_BIRTHDAY_CUE}[^\d\n]{{0,24}}(?P<day>\d{{1,2}})[./-](?P<month>\d{{1,2}})(?:[./-](?P<year>\d{{2,4}}))?"
)
_TEXT_BIRTHDAY_RE = re.compile(
    rf"(?i){_BIRTHDAY_CUE}[^\d\n]{{0,24}}(?P<day>\d{{1,2}})\s+(?P<month>{_MONTH_PATTERN})(?:\s+(?P<year>\d{{4}}))?"
)


@dataclass(slots=True)
class EnrichedContactData:
    """Contact fields inferred from user text and public profile data."""

    description: str
    tags: list[str]
    display_name: str | None = None
    birthday_day: int | None = None
    birthday_month: int | None = None
    birthday_year: int | None = None


def _normalize_spaces(value: str | None) -> str:
    if not value:
        return ""
    return _WHITESPACE_RE.sub(" ", value).strip()


def _normalize_tag(tag: str) -> str:
    cleaned = tag.lstrip("#").strip().lower()
    return f"#{cleaned}" if cleaned else ""


def _dedupe_tags(tags: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        normalized = _normalize_tag(tag)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) >= 5:
            break
    return result


def _title_case_if_needed(value: str) -> str:
    parts = [part for part in value.split() if part]
    if not parts:
        return value
    if any(any(char.isupper() for char in part) for part in parts):
        return " ".join(parts)
    return " ".join(part.capitalize() for part in parts)


def _clean_display_name(value: str | None, username: str) -> str | None:
    cleaned = _normalize_spaces(value)
    if not cleaned:
        return None
    if cleaned.lower() in {"unknown", username.lower(), f"@{username.lower()}"}:
        return None
    if not _CLEAN_NAME_RE.fullmatch(cleaned):
        return None
    return _title_case_if_needed(cleaned)


def _extract_name_from_description(description: str, username: str) -> str | None:
    clean_description = _normalize_spaces(description)
    if not clean_description:
        return None

    for pattern in _NAME_PATTERNS:
        match = pattern.search(clean_description)
        if not match:
            continue
        candidate = match.group(1).strip(" ,.;:()[]{}-–—")
        candidate = re.split(
            r"\s+(?:из|с|по|работает|учится|дизайнер|разработчик|коллега|друг|подруга|"
            r"знакомый|знакомая|ментор|фаундер|основатель|маркетолог|продуктолог|pm|devrel)\b",
            candidate,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        cleaned = _clean_display_name(candidate, username)
        if cleaned:
            return cleaned
    return None


def _collect_hashtags(*texts: str) -> list[str]:
    tags: list[str] = []
    for text in texts:
        if not text:
            continue
        tags.extend(f"#{match.lower()}" for match in _HASHTAG_RE.findall(text))
    return _dedupe_tags(tags)


def _collect_keyword_tags(*texts: str) -> list[str]:
    collected: list[str] = []
    for text in texts:
        if not text:
            continue
        for pattern, tag in _KEYWORD_TAGS:
            if pattern.search(text):
                collected.append(tag)
    return _dedupe_tags(collected)


def _normalize_year(raw_year: str | None) -> int | None:
    if not raw_year:
        return None
    if len(raw_year) != 4:
        return None
    year = int(raw_year)
    return year if 1900 <= year <= 2100 else None


def _build_birthday(day: int, month: int, year: int | None) -> tuple[int, int, int | None] | None:
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    try:
        date(year or 2000, month, day)
    except ValueError:
        return None
    return day, month, year


def _extract_birthday_from_text(text: str) -> tuple[int, int, int | None] | None:
    clean_text = _normalize_spaces(text)
    if not clean_text:
        return None

    numeric_match = _NUMERIC_BIRTHDAY_RE.search(clean_text)
    if numeric_match:
        birthday = _build_birthday(
            int(numeric_match.group("day")),
            int(numeric_match.group("month")),
            _normalize_year(numeric_match.group("year")),
        )
        if birthday:
            return birthday

    text_match = _TEXT_BIRTHDAY_RE.search(clean_text)
    if text_match:
        month_raw = text_match.group("month").lower()
        month = _MONTHS.get(month_raw)
        if month:
            birthday = _build_birthday(
                int(text_match.group("day")),
                month,
                _normalize_year(text_match.group("year")),
            )
            if birthday:
                return birthday

    return None


async def _safe_fetch_profile(username: str) -> UsernameValidationResult | None:
    try:
        return await validate_public_username(username)
    except (UsernameValidationUnavailable, ValueError):
        return None


async def enrich_contact_data(
    *,
    username: str,
    raw_description: str | None = None,
    suggested_display_name: str | None = None,
    profile: UsernameValidationResult | None = None,
    fetch_profile_if_missing: bool = True,
) -> EnrichedContactData:
    """Combine explicit text and public-profile hints into contact fields."""
    description = _normalize_spaces(raw_description)
    profile = profile or (await _safe_fetch_profile(username) if fetch_profile_if_missing else None)
    profile_exists = bool(profile and getattr(profile, "exists", False))

    profile_display_name = (
        _clean_display_name(getattr(profile, "display_name", None), username)
        if profile_exists
        else None
    )
    profile_about = _normalize_spaces(getattr(profile, "about_text", None)) if profile_exists else ""

    parsed_description = description
    ai_tags: list[str] = []
    ai_service = AIService()

    if description:
        parsed = await ai_service.parse_contact_input(description)
        if parsed:
            parsed_description = _normalize_spaces(parsed.description) or description
            ai_tags = parsed.tags
    elif profile_about:
        ai_tags = await ai_service.extract_tags(profile_about)

    tags = _dedupe_tags(
        _collect_hashtags(description, profile_about)
        + ai_tags
        + _collect_keyword_tags(parsed_description or description, profile_about)
    )

    display_name = (
        _clean_display_name(suggested_display_name, username)
        or _extract_name_from_description(parsed_description or description, username)
        or profile_display_name
    )

    birthday = _extract_birthday_from_text(description) or _extract_birthday_from_text(profile_about)

    return EnrichedContactData(
        description=parsed_description,
        tags=tags,
        display_name=display_name,
        birthday_day=birthday[0] if birthday else None,
        birthday_month=birthday[1] if birthday else None,
        birthday_year=birthday[2] if birthday else None,
    )
