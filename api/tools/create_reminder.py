"""create_reminder tool (S7).

Writes two things, both local:

  1. a row in the `reminders` table, and
  2. an RFC 5545 `.ics` file in `<vault>/reminders/`.

It notifies nobody and reaches no network. An `.ics` is just a text file;
the user's calendar app imports it if and when they choose to.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator

from api.tools._vault import relative_to_vault, slugify, unique_path, vault_path
from db.connect import connect

TOOL_NAME = "create_reminder"


class CreateReminderParams(BaseModel):
    """Validated parameters. The policy layer validates against this model
    before anything is written, so a malformed proposal never reaches disk."""

    title: str = Field(min_length=1, max_length=200)
    due_date: str = Field(description="ISO-8601 date, YYYY-MM-DD")
    notes: Optional[str] = Field(default=None, max_length=2000)
    source_document_hash: Optional[str] = Field(default=None, max_length=64)

    @field_validator("due_date")
    @classmethod
    def _must_be_iso_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value.strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"due_date must be an ISO-8601 date (YYYY-MM-DD), got {value!r}"
            ) from exc
        if not date(1970, 1, 1) <= parsed <= date(2200, 1, 1):
            raise ValueError(f"due_date {value!r} is outside a plausible range")
        return parsed.isoformat()

    @field_validator("title", "notes")
    @classmethod
    def _no_control_characters(cls, value: Optional[str]) -> Optional[str]:
        # Values may come from document text, which is untrusted: strip the
        # control characters that would corrupt the .ics line structure.
        if value is None:
            return None
        return "".join(ch for ch in value if ch == "\n" or ch >= " ").strip()


def _ics_escape(text: str) -> str:
    """RFC 5545 TEXT escaping: backslash, semicolon, comma, newline.

    Order matters -- backslashes must be doubled first, or the escapes
    added afterwards would themselves get escaped.
    """
    result = text or ""
    for raw, escaped in (
        ("\\", "\\\\"),
        (";", "\\;"),
        (",", "\\,"),
        ("\r\n", "\\n"),
        ("\n", "\\n"),
    ):
        result = result.replace(raw, escaped)
    return result


def build_ics(params: CreateReminderParams, uid: Optional[str] = None) -> str:
    """A minimal, valid all-day VEVENT with a one-day-before alarm."""
    due = date.fromisoformat(params.due_date)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//LifeVault//Local Reminder//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid or uuid.uuid4()}@lifevault.local",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{due.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{(due + timedelta(days=1)).strftime('%Y%m%d')}",
        f"SUMMARY:{_ics_escape(params.title)}",
    ]
    if params.notes:
        lines.append(f"DESCRIPTION:{_ics_escape(params.notes)}")
    lines += [
        "BEGIN:VALARM",
        "TRIGGER:-P1D",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_ics_escape(params.title)}",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    # RFC 5545 requires CRLF line endings.
    return "\r\n".join(lines) + "\r\n"


def create_reminder(
    parameters: Dict[str, Any],
    proposal_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Create the reminder row and its .ics file. Returns a result dict."""
    params = CreateReminderParams(**parameters)
    uid = str(uuid.uuid4())

    filename = f"{params.due_date}-{slugify(params.title, 'reminder')}.ics"
    path = unique_path(vault_path("reminders", filename))
    path.write_text(build_ics(params, uid), encoding="utf-8")

    conn = connect(db_path)
    try:
        cursor = conn.execute(
            "INSERT INTO reminders (title, due_date, notes, ics_path, "
            "proposal_id, source_document_hash) VALUES (?, ?, ?, ?, ?, ?)",
            (params.title, params.due_date, params.notes, str(path),
             proposal_id, params.source_document_hash),
        )
        reminder_id = cursor.lastrowid
    finally:
        conn.close()

    return {
        "tool": TOOL_NAME,
        "reminder_id": reminder_id,
        "title": params.title,
        "due_date": params.due_date,
        "ics_path": str(path),
        "vault_relative_path": relative_to_vault(path),
        "sent": False,
    }
