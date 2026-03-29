"""
Helpers for validating public Telegram usernames.
"""
from __future__ import annotations

import asyncio
from html import unescape
import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

logger = logging.getLogger(__name__)

USERNAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{4,31}$")
CACHE_TTL_SECONDS = 15 * 60


class UsernameValidationUnavailable(RuntimeError):
    """Raised when Telegram username validation cannot be completed."""


@dataclass(slots=True)
class UsernameValidationResult:
    """Validation result for a public Telegram username."""

    username: str
    exists: bool
    checked_url: str
    display_name: str | None = None
    about_text: str | None = None


_cache: dict[str, tuple[float, UsernameValidationResult]] = {}
_META_TAG_RE = re.compile(
    r'<meta[^>]+(?:property|name)="(?P<name>[^"]+)"[^>]+content="(?P<content>[^"]*)"',
    re.IGNORECASE,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _extract_meta_content(page_html: str, meta_name: str) -> str | None:
    target = meta_name.lower()
    for match in _META_TAG_RE.finditer(page_html):
        if match.group("name").lower() != target:
            continue
        content = unescape(match.group("content") or "").strip()
        return " ".join(content.split()) if content else None
    return None


def _strip_html(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = unescape(_HTML_TAG_RE.sub(" ", value))
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def _extract_title(page_html: str) -> str | None:
    match = re.search(r"<title>(.*?)</title>", page_html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return _strip_html(match.group(1))


def _extract_display_name(page_html: str, username: str) -> str | None:
    for candidate in (
        _extract_meta_content(page_html, "og:title"),
        _extract_meta_content(page_html, "twitter:title"),
        _extract_title(page_html),
    ):
        if not candidate:
            continue
        normalized = candidate.removeprefix("@").strip()
        lower_value = normalized.lower()
        if lower_value in {username.lower(), f"{username.lower()} telegram", f"telegram: {username.lower()}"}:
            continue
        if lower_value.startswith("telegram:"):
            normalized = normalized.split(":", 1)[1].strip()
        normalized = " ".join(normalized.split())
        if normalized and normalized.lower() != username.lower():
            return normalized
    return None


def _extract_about_text(page_html: str, username: str) -> str | None:
    generic_phrases = (
        "if you have telegram",
        "you can contact",
        "you can view and join",
        "preview channel",
    )
    for candidate in (
        _extract_meta_content(page_html, "og:description"),
        _extract_meta_content(page_html, "description"),
        _extract_meta_content(page_html, "twitter:description"),
    ):
        if not candidate:
            continue
        normalized = candidate.replace(f"@{username}", "").strip().lower()
        if any(phrase in normalized for phrase in generic_phrases):
            continue
        return candidate
    return None


def normalize_username(username: str) -> str:
    """Normalize a Telegram username for storage and validation."""
    normalized = username.strip().lstrip("@")
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("Invalid Telegram username format")
    return normalized.lower()


def _get_cached_result(username: str) -> UsernameValidationResult | None:
    cached = _cache.get(username)
    if not cached:
        return None

    expires_at, result = cached
    if expires_at <= time.time():
        _cache.pop(username, None)
        return None

    return result


def _set_cached_result(result: UsernameValidationResult) -> None:
    _cache[result.username] = (time.time() + CACHE_TTL_SECONDS, result)


def _is_existing_public_page(final_url: str, username: str, page_html: str) -> bool:
    parsed = urlsplit(final_url)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/").lower()
    if host not in {"t.me", "www.t.me"} or path != f"/{username}":
        return False
    return "tgme_page_title" in page_html


def _check_public_username(username: str) -> UsernameValidationResult:
    normalized = normalize_username(username)

    cached = _get_cached_result(normalized)
    if cached:
        return cached

    checked_url = f"https://t.me/{normalized}"

    try:
        response = requests.get(
            checked_url,
            allow_redirects=True,
            timeout=15,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/135.0 Safari/537.36"
                )
            },
        )
    except requests.RequestException as exc:
        logger.warning("Telegram username validation failed for @%s: %s", normalized, exc)
        raise UsernameValidationUnavailable("Validation request failed") from exc

    result = UsernameValidationResult(
        username=normalized,
        exists=_is_existing_public_page(response.url, normalized, response.text),
        checked_url=checked_url,
        display_name=_extract_display_name(response.text, normalized),
        about_text=_extract_about_text(response.text, normalized),
    )
    _set_cached_result(result)
    return result


async def validate_public_username(username: str) -> UsernameValidationResult:
    """Validate a public Telegram username via its public t.me page."""
    return await asyncio.to_thread(_check_public_username, username)
