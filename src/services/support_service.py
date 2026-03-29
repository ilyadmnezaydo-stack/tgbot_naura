"""
Local storage for support tickets and admin replies.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


@dataclass(slots=True)
class SupportTicket:
    """One support conversation entry."""

    id: str
    user_id: int
    user_username: str | None
    user_first_name: str | None
    question: str
    source: str
    status: str
    parent_ticket_id: str | None
    ai_answer: str | None
    admin_reply: str | None
    admin_id: int | None
    feedback: str | None
    created_at: datetime
    updated_at: datetime
    answered_at: datetime | None


_STORE_LOCK = asyncio.Lock()
_STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "support_tickets.json"


def _ensure_store_dir() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_store() -> list[dict]:
    if not _STORE_PATH.exists():
        return []

    try:
        with _STORE_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_store(data: list[dict]) -> None:
    _ensure_store_dir()
    temp_path = _STORE_PATH.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    temp_path.replace(_STORE_PATH)


def _to_ticket(raw: dict) -> SupportTicket:
    return SupportTicket(
        id=raw["id"],
        user_id=raw["user_id"],
        user_username=raw.get("user_username"),
        user_first_name=raw.get("user_first_name"),
        question=raw["question"],
        source=raw.get("source", "initial"),
        status=raw.get("status", "pending_admin"),
        parent_ticket_id=raw.get("parent_ticket_id"),
        ai_answer=raw.get("ai_answer"),
        admin_reply=raw.get("admin_reply"),
        admin_id=raw.get("admin_id"),
        feedback=raw.get("feedback"),
        created_at=datetime.fromisoformat(raw["created_at"]),
        updated_at=datetime.fromisoformat(raw["updated_at"]),
        answered_at=datetime.fromisoformat(raw["answered_at"]) if raw.get("answered_at") else None,
    )


def _to_row(ticket: SupportTicket) -> dict:
    return {
        "id": ticket.id,
        "user_id": ticket.user_id,
        "user_username": ticket.user_username,
        "user_first_name": ticket.user_first_name,
        "question": ticket.question,
        "source": ticket.source,
        "status": ticket.status,
        "parent_ticket_id": ticket.parent_ticket_id,
        "ai_answer": ticket.ai_answer,
        "admin_reply": ticket.admin_reply,
        "admin_id": ticket.admin_id,
        "feedback": ticket.feedback,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
        "answered_at": ticket.answered_at.isoformat() if ticket.answered_at else None,
    }


async def list_support_tickets() -> list[SupportTicket]:
    """Return all support tickets from local storage."""
    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)

    tickets = [_to_ticket(raw) for raw in data if isinstance(raw, dict)]
    tickets.sort(key=lambda item: item.created_at, reverse=True)
    return tickets


async def create_support_ticket(
    *,
    user_id: int,
    user_username: str | None,
    user_first_name: str | None,
    question: str,
    source: str = "initial",
    status: str = "pending_admin",
    parent_ticket_id: str | None = None,
    ai_answer: str | None = None,
    admin_reply: str | None = None,
    admin_id: int | None = None,
    feedback: str | None = None,
    created_at: datetime,
) -> SupportTicket:
    """Persist a support ticket and return it."""
    ticket = SupportTicket(
        id=str(uuid4()),
        user_id=user_id,
        user_username=user_username,
        user_first_name=user_first_name,
        question=question,
        source=source,
        status=status,
        parent_ticket_id=parent_ticket_id,
        ai_answer=ai_answer,
        admin_reply=admin_reply,
        admin_id=admin_id,
        feedback=feedback,
        created_at=created_at,
        updated_at=created_at,
        answered_at=None,
    )

    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)
        data.insert(0, _to_row(ticket))
        await asyncio.to_thread(_write_store, data)

    return ticket


async def get_support_ticket(ticket_id: str) -> SupportTicket | None:
    """Load one support ticket by id."""
    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)

    for raw in data:
        if raw.get("id") == ticket_id:
            return _to_ticket(raw)
    return None


async def update_support_ticket(ticket_id: str, **updates) -> SupportTicket | None:
    """Update one support ticket in local storage."""
    async with _STORE_LOCK:
        data = await asyncio.to_thread(_load_store)

        for index, raw in enumerate(data):
            if raw.get("id") != ticket_id:
                continue

            ticket = _to_ticket(raw)
            for key, value in updates.items():
                if hasattr(ticket, key):
                    setattr(ticket, key, value)

            if "updated_at" not in updates:
                tzinfo = ticket.updated_at.tzinfo or ticket.created_at.tzinfo
                ticket.updated_at = datetime.now(tzinfo) if tzinfo else datetime.utcnow()

            data[index] = _to_row(ticket)
            await asyncio.to_thread(_write_store, data)
            return ticket

    return None


def support_ticket_to_namespace(ticket: SupportTicket) -> SimpleNamespace:
    """Convert a ticket to dot-access namespace for convenient formatting."""
    return SimpleNamespace(
        id=ticket.id,
        user_id=ticket.user_id,
        user_username=ticket.user_username,
        user_first_name=ticket.user_first_name,
        question=ticket.question,
        source=ticket.source,
        status=ticket.status,
        parent_ticket_id=ticket.parent_ticket_id,
        ai_answer=ticket.ai_answer,
        admin_reply=ticket.admin_reply,
        admin_id=ticket.admin_id,
        feedback=ticket.feedback,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        answered_at=ticket.answered_at,
    )
