"""
Lightweight local analytics storage for owner dashboard metrics.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(slots=True)
class ButtonUsageStat:
    """Aggregated usage statistics for one tracked button."""

    key: str
    label: str
    count: int
    last_clicked_at: datetime | None = None


@dataclass(slots=True)
class AnalyticsEvent:
    """One user interaction recorded for time-based analytics."""

    event_type: str
    user_id: int
    occurred_at: datetime
    button_key: str | None = None
    label: str | None = None


_STORE_LOCK = asyncio.Lock()
_STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "bot_analytics.json"


def _ensure_store_dir() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _empty_store() -> dict:
    return {"user_last_seen": {}, "button_clicks": {}, "events": []}


def _normalize_store(raw_data: dict | None) -> dict:
    if not isinstance(raw_data, dict):
        return _empty_store()

    data = dict(raw_data)
    if not isinstance(data.get("user_last_seen"), dict):
        data["user_last_seen"] = {}
    if not isinstance(data.get("button_clicks"), dict):
        data["button_clicks"] = {}
    if not isinstance(data.get("events"), list):
        data["events"] = []
    return data


def _load_store() -> dict:
    if not _STORE_PATH.exists():
        return _empty_store()

    try:
        with _STORE_PATH.open("r", encoding="utf-8") as fh:
            return _normalize_store(json.load(fh))
    except (json.JSONDecodeError, OSError):
        return _empty_store()


def _write_store(data: dict) -> None:
    _ensure_store_dir()
    temp_path = _STORE_PATH.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    temp_path.replace(_STORE_PATH)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_datetime(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _deserialize_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _append_event(
    data: dict,
    *,
    event_type: str,
    user_id: int,
    occurred_at: datetime,
    button_key: str | None = None,
    label: str | None = None,
) -> None:
    data.setdefault("events", []).append(
        {
            "event_type": event_type,
            "user_id": user_id,
            "occurred_at": _serialize_datetime(occurred_at),
            "button_key": button_key,
            "label": label,
        }
    )


async def record_interaction(
    user_id: int,
    occurred_at: datetime | None = None,
) -> None:
    """Update the last-seen time for a user interaction."""
    event_time = occurred_at or _utc_now()
    timestamp = _serialize_datetime(event_time)

    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)
        data.setdefault("user_last_seen", {})[str(user_id)] = timestamp
        _append_event(data, event_type="interaction", user_id=user_id, occurred_at=event_time)
        await asyncio.to_thread(_write_store, data)


async def record_button_click(
    user_id: int,
    button_key: str,
    label: str,
    occurred_at: datetime | None = None,
) -> None:
    """Track one button click and also refresh the user's last-seen timestamp."""
    event_time = occurred_at or _utc_now()
    event_time_str = _serialize_datetime(event_time)

    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)
        data.setdefault("user_last_seen", {})[str(user_id)] = event_time_str

        button_stats = data.setdefault("button_clicks", {})
        entry = button_stats.setdefault(
            button_key,
            {
                "label": label,
                "count": 0,
                "last_clicked_at": event_time_str,
            },
        )
        entry["label"] = label
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last_clicked_at"] = event_time_str
        _append_event(
            data,
            event_type="button_click",
            user_id=user_id,
            occurred_at=event_time,
            button_key=button_key,
            label=label,
        )

        await asyncio.to_thread(_write_store, data)


async def get_active_user_count(user_ids: list[int], within_days: int = 7) -> int:
    """Count users who interacted with the bot within the given number of days."""
    threshold = _utc_now() - timedelta(days=within_days)

    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)

    last_seen = data.get("user_last_seen", {})
    active = 0
    for user_id in user_ids:
        value = _deserialize_datetime(last_seen.get(str(user_id)))
        if value and value >= threshold:
            active += 1
    return active


async def get_user_last_seen_map() -> dict[int, datetime]:
    """Return the recorded last-seen time for each user."""
    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)

    last_seen_map: dict[int, datetime] = {}
    for raw_user_id, raw_value in (data.get("user_last_seen") or {}).items():
        try:
            user_id = int(raw_user_id)
        except (TypeError, ValueError):
            continue

        parsed = _deserialize_datetime(raw_value)
        if parsed:
            last_seen_map[user_id] = parsed
    return last_seen_map


async def list_analytics_events() -> list[AnalyticsEvent]:
    """Return recorded analytics events for period-based dashboards."""
    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)

    events: list[AnalyticsEvent] = []
    for raw_event in data.get("events") or []:
        if not isinstance(raw_event, dict):
            continue

        occurred_at = _deserialize_datetime(raw_event.get("occurred_at"))
        if not occurred_at:
            continue

        try:
            user_id = int(raw_event.get("user_id"))
        except (TypeError, ValueError):
            continue

        events.append(
            AnalyticsEvent(
                event_type=str(raw_event.get("event_type") or "interaction"),
                user_id=user_id,
                occurred_at=occurred_at,
                button_key=raw_event.get("button_key"),
                label=raw_event.get("label"),
            )
        )

    events.sort(key=lambda item: item.occurred_at)
    return events


async def get_button_click_stats() -> list[ButtonUsageStat]:
    """Return aggregated button usage stats across all time."""
    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)

    stats: list[ButtonUsageStat] = []
    for key, raw_entry in (data.get("button_clicks") or {}).items():
        if not isinstance(raw_entry, dict):
            continue
        stats.append(
            ButtonUsageStat(
                key=key,
                label=str(raw_entry.get("label") or key),
                count=int(raw_entry.get("count") or 0),
                last_clicked_at=_deserialize_datetime(raw_entry.get("last_clicked_at")),
            )
        )

    stats.sort(key=lambda item: (-item.count, item.label.lower()))
    return stats


async def get_top_button_clicks(limit: int = 10) -> list[ButtonUsageStat]:
    """Return the most clicked tracked buttons."""
    stats = await get_button_click_stats()
    return stats[:limit]
