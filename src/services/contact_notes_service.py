"""
Lightweight local storage for per-contact conversation notes.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class ContactNote:
    """A saved note attached to a contact."""

    text: str
    created_at: datetime


@dataclass(slots=True)
class ContactNoteEntry:
    """A saved note with the owning contact id attached."""

    contact_id: str
    text: str
    created_at: datetime


_STORE_LOCK = asyncio.Lock()
_MAX_NOTES_PER_CONTACT = 25
_STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "contact_notes.json"


def _ensure_store_dir() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_store() -> dict[str, list[dict[str, str]]]:
    if not _STORE_PATH.exists():
        return {}

    try:
        with _STORE_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_store(data: dict[str, list[dict[str, str]]]) -> None:
    _ensure_store_dir()
    temp_path = _STORE_PATH.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    temp_path.replace(_STORE_PATH)


def _deserialize_note(raw_note: dict[str, str] | None) -> ContactNote | None:
    if not raw_note:
        return None

    text = (raw_note.get("text") or "").strip()
    created_at = raw_note.get("created_at")
    if not text or not created_at:
        return None

    return ContactNote(
        text=text,
        created_at=datetime.fromisoformat(created_at),
    )


async def add_contact_note(
    contact_id: str,
    text: str,
    created_at: datetime,
) -> ContactNote:
    """Save a new note for a contact and return the saved object."""
    clean_text = text.strip()
    note = ContactNote(text=clean_text, created_at=created_at)

    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)
        notes = data.setdefault(contact_id, [])
        notes.insert(
            0,
            {
                "text": clean_text,
                "created_at": created_at.isoformat(),
            },
        )
        del notes[_MAX_NOTES_PER_CONTACT:]
        await asyncio.to_thread(_write_store, data)

    return note


async def get_latest_contact_note(contact_id: str) -> ContactNote | None:
    """Return the latest saved note for a contact, if any."""
    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)

    notes = data.get(contact_id) or []
    return _deserialize_note(notes[0] if notes else None)


async def list_contact_notes(contact_ids: set[str] | None = None) -> list[ContactNoteEntry]:
    """Return all saved notes, optionally limited to a set of contact ids."""
    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)

    entries: list[ContactNoteEntry] = []
    for contact_id, raw_notes in data.items():
        if contact_ids is not None and contact_id not in contact_ids:
            continue

        for raw_note in raw_notes or []:
            note = _deserialize_note(raw_note)
            if not note:
                continue

            entries.append(
                ContactNoteEntry(
                    contact_id=contact_id,
                    text=note.text,
                    created_at=note.created_at,
                )
            )

    return entries


async def delete_contact_notes(contact_id: str) -> None:
    """Delete all saved notes for a contact."""
    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)
        if contact_id not in data:
            return
        data.pop(contact_id, None)
        await asyncio.to_thread(_write_store, data)
