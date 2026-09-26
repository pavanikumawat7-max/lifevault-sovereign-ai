"""Append-only, hash-chained audit log.

This is the ONE piece of real feature logic in LifeVault S1. Everything
else in the repo is a typed stub -- this module actually works and is
actually tested.

Design
------
Each row commits: event, canonicalized payload, timestamp, the previous
row's hash, and this row's own hash. The row hash is a SHA-256 digest over
(prev_hash | event | ts | payload_json), so any edit to any historical
row -- payload, event, timestamp, or an attempt to splice/reorder rows --
breaks the chain from that point forward and `verify()` detects it
deterministically.

Deliberately implemented with the standard library only (sqlite3,
hashlib, json, datetime) so it has zero dependency on pydantic/FastAPI and
can be fully unit tested without the rest of the stack installed. The API
route layer (api/routes/audit.py) wraps this module's plain-dict output in
the frozen Pydantic response models.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

GENESIS_HASH = "0" * 64


class AuditError(Exception):
    """Base class for audit-log errors."""


class TamperDetectedError(AuditError):
    """Raised by callers that want verify() failures to be exceptions."""


def _canonicalize(payload: dict) -> str:
    """Stable JSON encoding used for both storage and hashing.

    Sorted keys + no incidental whitespace so the same logical payload
    always canonicalizes to the same bytes, on any machine, any Python
    version. `default=str` keeps this from blowing up on odd-but-honest
    values (e.g. a stray datetime) without ever silently dropping data.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _row_hash(event: str, payload_json: str, ts: str, prev_hash: str) -> str:
    digest = hashlib.sha256()
    digest.update(prev_hash.encode("utf-8"))
    digest.update(b"|")
    digest.update(event.encode("utf-8"))
    digest.update(b"|")
    digest.update(ts.encode("utf-8"))
    digest.update(b"|")
    digest.update(payload_json.encode("utf-8"))
    return digest.hexdigest()


class AuditLog:
    """Bound to a single sqlite3.Connection (see db/connect.py)."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def log(self, event: str, payload: Optional[dict] = None) -> dict:
        """Append one audit row and return it as a plain dict.

        Transactional: the read of the previous row's hash and the insert
        of the new row happen inside a single BEGIN IMMEDIATE ... COMMIT,
        so two concurrent writers can't both read the same prev_hash and
        silently fork the chain. On any failure the transaction is rolled
        back and no partial row is left behind.
        """
        payload = payload if payload is not None else {}
        payload_json = _canonicalize(payload)
        ts = datetime.now(timezone.utc).isoformat()

        cur = self._conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            cur.execute("SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            prev_hash = row[0] if row is not None else GENESIS_HASH
            row_hash = _row_hash(event, payload_json, ts, prev_hash)
            cur.execute(
                "INSERT INTO audit_log (event, payload, ts, prev_hash, row_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (event, payload_json, ts, prev_hash, row_hash),
            )
            new_id = cur.lastrowid
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        return {
            "id": new_id,
            "event": event,
            "payload": payload,
            "ts": ts,
            "prev_hash": prev_hash,
            "row_hash": row_hash,
        }

    def verify(self) -> dict:
        """Walk the whole chain and confirm every link is intact.

        Returns a plain dict (matching api.schemas.AuditVerifyResponse):
            {"valid": bool, "reason": str | None, "row_id": int | None,
             "rows_checked": int}

        `reason`/`row_id` identify the first broken link, if any. An empty
        audit_log is trivially valid (rows_checked == 0).
        """
        cur = self._conn.cursor()
        cur.execute(
            "SELECT id, event, payload, ts, prev_hash, row_hash "
            "FROM audit_log ORDER BY id ASC"
        )
        rows = cur.fetchall()

        expected_prev = GENESIS_HASH
        checked = 0
        for row_id, event, payload_json, ts, prev_hash, row_hash in rows:
            if prev_hash != expected_prev:
                return {
                    "valid": False,
                    "reason": "prev_hash_mismatch",
                    "row_id": row_id,
                    "rows_checked": checked,
                }
            recomputed = _row_hash(event, payload_json, ts, prev_hash)
            if recomputed != row_hash:
                return {
                    "valid": False,
                    "reason": "row_hash_mismatch",
                    "row_id": row_id,
                    "rows_checked": checked,
                }
            expected_prev = row_hash
            checked += 1

        return {"valid": True, "reason": None, "row_id": None, "rows_checked": checked}

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        """Convenience read path used by the /api/audit route."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT id, event, payload, ts, prev_hash, row_hash "
            "FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "id": r[0],
                "event": r[1],
                "payload": json.loads(r[2]),
                "ts": r[3],
                "prev_hash": r[4],
                "row_hash": r[5],
            }
            for r in cur.fetchall()
        ]
