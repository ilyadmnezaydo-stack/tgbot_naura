"""
Helpers to convert Supabase dict responses to SimpleNamespace objects.
Preserves dot-notation access (contact.username, contact.id, etc.).
"""
from datetime import date, datetime
from types import SimpleNamespace


def _parse_value(key: str, value):
    """Parse ISO date/datetime strings back to Python objects."""
    if value is None:
        return None
    if key in ("next_reminder_date", "one_time_date") and isinstance(value, str):
        return date.fromisoformat(value)
    if key in ("created_at", "updated_at", "last_contacted_at") and isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def to_record(row: dict | None) -> SimpleNamespace | None:
    """Convert a single Supabase response dict to SimpleNamespace."""
    if row is None:
        return None
    return SimpleNamespace(**{k: _parse_value(k, v) for k, v in row.items()})


def to_records(rows: list[dict]) -> list[SimpleNamespace]:
    """Convert a list of Supabase response dicts to SimpleNamespace objects."""
    return [to_record(row) for row in rows]
