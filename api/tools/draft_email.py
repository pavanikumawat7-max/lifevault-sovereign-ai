"""draft_email tool (S7).

Writes an RFC 5322 `.eml` file into `<vault>/drafts/`. It **never sends,
queues, or transmits anything** -- there is no SMTP client in this module
and there must never be one. The result dict always reports `sent: False`,
and the draft carries an `X-LifeVault-Draft: true` header so it is obvious
in any mail client that this was never transmitted.
"""
from __future__ import annotations

from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from api.tools._vault import relative_to_vault, slugify, unique_path, vault_path

TOOL_NAME = "draft_email"

_MAX_RECIPIENTS = 5


class DraftEmailParams(BaseModel):
    """Validated parameters.

    `to` is accepted and written into the draft headers but nothing is ever
    sent to it. Recipients are capped and shape-checked so a value lifted
    out of document text cannot inject extra headers.
    """

    to: List[str] = Field(default_factory=list, max_length=_MAX_RECIPIENTS)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    source_document_hash: Optional[str] = Field(default=None, max_length=64)

    @field_validator("to")
    @classmethod
    def _plausible_addresses(cls, values: List[str]) -> List[str]:
        cleaned: List[str] = []
        for value in values:
            address = (value or "").strip()
            if not address:
                continue
            # Header injection guard: no newlines, and it must look like an
            # address rather than arbitrary document text.
            if any(ch in address for ch in "\r\n") or address.count("@") != 1:
                raise ValueError(f"not a valid email address: {value!r}")
            local, _, domain = address.partition("@")
            if not local or "." not in domain:
                raise ValueError(f"not a valid email address: {value!r}")
            cleaned.append(address)
        return cleaned

    @field_validator("subject")
    @classmethod
    def _single_line_subject(cls, value: str) -> str:
        if any(ch in value for ch in "\r\n"):
            raise ValueError("subject must be a single line")
        return value.strip()


def build_eml(params: DraftEmailParams) -> bytes:
    """Serialize the draft. Uses the stdlib so headers are escaped properly."""
    message = EmailMessage()
    message["Subject"] = params.subject
    message["From"] = "LifeVault Draft <draft@lifevault.local>"
    if params.to:
        message["To"] = ", ".join(params.to)
    message["Date"] = format_datetime(datetime.now(timezone.utc))
    message["Message-ID"] = make_msgid(domain="lifevault.local")
    # Unmistakable marker: this file was written locally and never sent.
    message["X-LifeVault-Draft"] = "true"
    message["X-Unsent"] = "1"
    message.set_content(params.body)
    return message.as_bytes()


def draft_email(
    parameters: Dict[str, Any],
    proposal_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the .eml draft. Never sends. Returns a result dict."""
    params = DraftEmailParams(**parameters)

    stem = slugify(params.subject, "draft")
    filename = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{stem}.eml"
    path = unique_path(vault_path("drafts", filename))
    path.write_bytes(build_eml(params))

    return {
        "tool": TOOL_NAME,
        "subject": params.subject,
        "to": params.to,
        "eml_path": str(path),
        "vault_relative_path": relative_to_vault(path),
        # Invariant, asserted in tests: this tool never transmits.
        "sent": False,
    }
