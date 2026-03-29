"""
Hybrid contact search handler with deterministic tag/context ranking.
"""
from __future__ import annotations

import re
from typing import Iterable

from telegram import Update
from telegram.ext import ContextTypes

from src.bot.handlers.callbacks import send_contact_card
from src.bot.input_text import get_input_text
from src.db.engine import get_supabase
from src.db.repositories.contacts import ContactRepository
from src.services.ai_service import AIService
from src.services.contact_enrichment import _KEYWORD_TAGS

_HASHTAG_RE = re.compile(r"#([\w/-]+)", flags=re.UNICODE)
_TOKEN_RE = re.compile(r"[@#]?[\w/-]+", flags=re.UNICODE)
_RU_SUFFIXES = (
    "иями",
    "ями",
    "ами",
    "его",
    "ого",
    "ему",
    "ому",
    "ыми",
    "ими",
    "иях",
    "ах",
    "ях",
    "ов",
    "ев",
    "ей",
    "ам",
    "ям",
    "ом",
    "ем",
    "ий",
    "ый",
    "ой",
    "ая",
    "яя",
    "ое",
    "ее",
    "ие",
    "ые",
    "а",
    "я",
    "у",
    "ю",
    "е",
    "и",
    "ы",
    "о",
    "ь",
)
_EN_SUFFIXES = ("ing", "ers", "ies", "es", "s")
_QUERY_STOPWORDS = {
    "а",
    "без",
    "в",
    "во",
    "где",
    "для",
    "и",
    "из",
    "или",
    "ищи",
    "ищу",
    "как",
    "какая",
    "какие",
    "какой",
    "кого",
    "контакт",
    "контакта",
    "контакты",
    "кто",
    "ли",
    "мне",
    "можно",
    "на",
    "надо",
    "найди",
    "нужен",
    "нужна",
    "нужны",
    "о",
    "об",
    "обычный",
    "обычные",
    "обычных",
    "он",
    "она",
    "они",
    "от",
    "по",
    "под",
    "покажи",
    "пожалуйста",
    "про",
    "с",
    "со",
    "среди",
    "у",
    "что",
    "это",
    "эти",
    "этот",
    "эта",
}
_SEARCH_INTENT_PREFIXES = (
    "где ",
    "ищи ",
    "ищу ",
    "кого ",
    "кто ",
    "найди ",
    "найти ",
    "покажи ",
)
_SEARCH_INTENT_PHRASES = (
    "кто у меня",
    "поиск ",
    "контакты ",
)


def _normalize_text(value: str | None) -> str:
    """Normalize text for case-insensitive matching."""
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def _normalize_token(value: str | None) -> str:
    """Normalize one search token while preserving internal separators."""
    if not value:
        return ""
    return value.strip().lower().lstrip("#@").strip(".,!?;:()[]{}\"'")


def _stem_token(token: str) -> str:
    """Apply light stemming so inflected forms still match stored tags/context."""
    normalized = _normalize_token(token)
    if len(normalized) < 4:
        return normalized

    suffixes = _RU_SUFFIXES if re.search(r"[а-яё]", normalized, flags=re.IGNORECASE) else _EN_SUFFIXES
    for suffix in suffixes:
        if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 4:
            return normalized[: -len(suffix)]
    return normalized


def _terms_match(left: str, right: str) -> bool:
    """Return True when two words are close enough to represent the same idea."""
    normalized_left = _normalize_token(left)
    normalized_right = _normalize_token(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True

    stemmed_left = _stem_token(normalized_left)
    stemmed_right = _stem_token(normalized_right)
    if stemmed_left and stemmed_left == stemmed_right:
        return True

    shorter, longer = sorted((stemmed_left, stemmed_right), key=len)
    return len(shorter) >= 4 and longer.startswith(shorter)


def _extract_query_tags(query: str) -> set[str]:
    """Extract explicit hashtags from the user query."""
    return {
        f"#{_normalize_token(raw_tag)}"
        for raw_tag in _HASHTAG_RE.findall(query or "")
        if _normalize_token(raw_tag)
    }


def _infer_query_tags(query: str) -> set[str]:
    """Infer canonical tags from natural-language queries without the LLM."""
    normalized_query = _normalize_text(query)
    tags = set(_extract_query_tags(normalized_query))
    for pattern, tag in _KEYWORD_TAGS:
        if pattern.search(normalized_query):
            tags.add(tag.lower())
    return tags


def _extract_query_words(query: str) -> list[str]:
    """Extract meaningful words from a query, including Russian text."""
    result: list[str] = []
    seen: set[str] = set()

    for part in _TOKEN_RE.findall(query or ""):
        normalized = _normalize_token(part)
        if (
            not normalized
            or part.startswith("#")
            or normalized in _QUERY_STOPWORDS
            or len(normalized) < 2
        ):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)

    return result


def _extract_context_words(*parts: str | None) -> list[str]:
    """Collect unique searchable words from contact fields."""
    result: list[str] = []
    seen: set[str] = set()

    for part in parts:
        for token in _TOKEN_RE.findall(part or ""):
            normalized = _normalize_token(token)
            if not normalized or len(normalized) < 2 or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)

    return result


def _score_tag_match(contact, query: str) -> int:
    """Prioritize direct tag hits before any context matching."""
    normalized_query = _normalize_text(query)
    query_tags = _infer_query_tags(normalized_query)
    query_words = _extract_query_words(normalized_query)
    contact_tags = [
        _normalize_token(tag)
        for tag in (getattr(contact, "tags", None) or [])
        if _normalize_token(tag)
    ]

    if not contact_tags:
        return 0

    score = 0

    if query_tags:
        contact_tag_set = {f"#{tag}" for tag in contact_tags}
        if query_tags.issubset(contact_tag_set):
            score = max(score, 220 + (len(query_tags) * 10))

    if normalized_query:
        for tag in contact_tags:
            if normalized_query in {tag, f"#{tag}"}:
                score = max(score, 210)

    matched_terms = 0
    for query_word in query_words:
        if any(_terms_match(query_word, contact_tag) for contact_tag in contact_tags):
            matched_terms += 1

    if matched_terms:
        score = max(score, 180 + (matched_terms * 10))

    return score


def _score_context_match(contact, query: str) -> int:
    """Rank matches by description/context after tag matches."""
    normalized_query = _normalize_text(query)
    query_words = _extract_query_words(normalized_query)
    username = _normalize_text(getattr(contact, "username", None))
    display_name = _normalize_text(getattr(contact, "display_name", None))
    description = _normalize_text(getattr(contact, "description", None))

    score = 0

    if normalized_query and normalized_query in {username, f"@{username}"}:
        score = max(score, 170)
    elif username and any(_terms_match(query_word, username) for query_word in query_words):
        score = max(score, 155)

    if display_name and normalized_query == display_name:
        score = max(score, 165)
    elif display_name and normalized_query and normalized_query in display_name:
        score = max(score, 150)

    if description and normalized_query and normalized_query in description:
        score = max(score, 145)

    if query_words:
        context_words = _extract_context_words(username, display_name, description)
        matched_terms = 0
        for query_word in query_words:
            if any(_terms_match(query_word, context_word) for context_word in context_words):
                matched_terms += 1
        if matched_terms:
            score = max(score, 120 + (matched_terms * 10))

    return score


def _sort_scored_matches(scored_matches: Iterable[tuple[int, int, object]]) -> list:
    """Sort by descending score, preserving original order for ties."""
    return [contact for _, _, contact in sorted(scored_matches, key=lambda item: (-item[0], item[1]))]


def _find_tag_matches(query: str, contacts: list) -> list:
    """Find contacts whose saved tags best match the query."""
    scored_matches = []
    for index, contact in enumerate(contacts):
        score = _score_tag_match(contact, query)
        if score > 0:
            scored_matches.append((score, index, contact))
    return _sort_scored_matches(scored_matches)


def _find_context_matches(query: str, contacts: list, excluded_ids: set) -> list:
    """Find contacts by username, display name, or saved description."""
    scored_matches = []
    for index, contact in enumerate(contacts):
        contact_id = getattr(contact, "id", None)
        if contact_id in excluded_ids:
            continue
        score = _score_context_match(contact, query)
        if score > 0:
            scored_matches.append((score, index, contact))
    return _sort_scored_matches(scored_matches)


def _merge_search_results(*groups: list) -> list:
    """Merge ranked result groups without duplicates."""
    merged = []
    seen_ids = set()

    for group in groups:
        for contact in group:
            contact_id = getattr(contact, "id", None)
            if contact_id in seen_ids:
                continue
            seen_ids.add(contact_id)
            merged.append(contact)

    return merged


def _build_search_summary(
    *,
    total: int,
    tag_count: int,
    context_count: int,
    semantic_count: int,
) -> str:
    """Explain the final search order to the user."""
    parts = []
    if tag_count:
        parts.append(f"сначала теги ({tag_count})")
    if context_count:
        parts.append(f"потом контекст ({context_count})")
    if semantic_count:
        parts.append(f"в конце AI-fallback ({semantic_count})")

    details = ", ".join(parts) if parts else "показал только точные совпадения"
    return f"🔎 <b>Нашёл {total}</b>\n{details}."


def _resolve_search_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str | None,
) -> str:
    """Use the explicit query when available, otherwise reuse current text/voice input."""
    if query and query.strip():
        return query.strip()
    return (get_input_text(update, context, strip=True) or "").strip()


def looks_like_search_query(query: str | None) -> bool:
    """Recognize common free-form search requests, especially from voice input."""
    normalized_query = _normalize_text(query)
    if not normalized_query:
        return False

    if normalized_query.startswith(_SEARCH_INTENT_PREFIXES):
        return True

    return any(phrase in normalized_query for phrase in _SEARCH_INTENT_PHRASES)


async def perform_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str | None = None,
) -> None:
    """Search contacts in a stable order: tags first, context second, AI last."""
    resolved_query = _resolve_search_query(update, context, query)
    if not resolved_query:
        await update.message.reply_text(
            "Напиши, кого ищешь, обычным сообщением или голосовым.",
            parse_mode="HTML",
        )
        return

    user_id = update.effective_user.id

    client = await get_supabase()
    repo = ContactRepository(client)
    all_contacts = await repo.get_all_for_user(user_id)

    if not all_contacts:
        await update.message.reply_text(
            "Сначала сохрани хотя бы один контакт через «✨ Добавить».",
            parse_mode="HTML",
        )
        return

    await update.message.chat.send_action("typing")

    tag_matches = _find_tag_matches(resolved_query, all_contacts)
    tag_match_ids = {getattr(contact, "id", None) for contact in tag_matches}
    context_matches = _find_context_matches(resolved_query, all_contacts, tag_match_ids)

    semantic_matches: list = []
    if not tag_matches and not context_matches:
        ai_service = AIService()
        semantic_matches = await ai_service.semantic_search(query=resolved_query, contacts=all_contacts)

    matching = _merge_search_results(tag_matches, context_matches, semantic_matches)

    if not matching:
        await update.message.reply_text(
            "Ничего подходящего не нашлось.\n"
            "Попробуй уточнить формулировку или открыть «👥 Контакты».",
            parse_mode="HTML",
        )
        return

    await update.message.reply_text(
        _build_search_summary(
            total=len(matching),
            tag_count=len(tag_matches),
            context_count=len(context_matches),
            semantic_count=max(0, len(matching) - len(tag_matches) - len(context_matches)),
        ),
        parse_mode="HTML",
    )

    for contact in matching:
        await send_contact_card(update.message, contact)
