#!/usr/bin/env python3
"""Smoke test: verifies every required S1 API endpoint exists and returns
an acceptable, typed JSON response.

Uses fastapi.testclient.TestClient (in-process, via httpx) rather than
spawning a real uvicorn server, so it needs no free port and no network --
it fails clearly and immediately if fastapi/pydantic aren't installed, if
an endpoint is missing (404), or if a response doesn't parse as JSON /
doesn't have the expected status code.

Run with: python scripts/smoke.py
Exit code 0 = all checks passed. Non-zero = at least one check failed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fastapi.testclient import TestClient
except ImportError as exc:  # pragma: no cover
    print(
        "FATAL: fastapi (and/or httpx) is not installed. "
        "Run `pip install -r requirements.txt` first.\n"
        f"Import error: {exc}"
    )
    sys.exit(1)

import tempfile

os.environ.setdefault("LIFEVAULT_DB_PATH", "/tmp/lifevault_smoke.db")
os.environ.setdefault("LIFEVAULT_USE_FIXTURES", "true")
# S7 tools write real files. Point the vault at a throwaway directory so a
# smoke run never leaves .ics/.eml files in the project's own vault/.
os.environ.setdefault(
    "LIFEVAULT_VAULT_DIR",
    str(Path(tempfile.gettempdir()) / "lifevault_smoke_vault"),
)

from config import get_config, reset_config_cache  # noqa: E402

reset_config_cache()

RESULTS: list[tuple[str, str, bool, str]] = []


def check(client, method: str, path: str, expected_status: int = 200, json_body=None) -> bool:
    try:
        resp = client.request(method, path, json=json_body)
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((method, path, False, f"request raised: {exc}"))
        print(f"[FAIL] {method:6s} {path:35s} -> exception: {exc}")
        return False

    status_ok = resp.status_code == expected_status
    try:
        resp.json()
        json_ok = True
    except Exception:
        json_ok = False

    ok = status_ok and json_ok
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {method:6s} {path:35s} -> {resp.status_code}")
    if not ok:
        detail = (
            f"expected status {expected_status}, got {resp.status_code}; "
            f"json_parseable={json_ok}; body={resp.text[:200]!r}"
        )
        print(f"        {detail}")
        RESULTS.append((method, path, False, detail))
    else:
        RESULTS.append((method, path, True, ""))
    return ok


def _seed_fact_and_proposal() -> None:
    """Insert one fact and three pending proposals for the real S6/S7 routes."""
    import json

    from db.connect import connect

    conn = connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO documents (content_hash, title) "
            "VALUES ('smoke-doc-1', 'dell_warranty.pdf')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO facts (id, type, field, value, norm_value, "
            "source_document_hash, source_quote) VALUES (1, 'warranty', "
            "'expiry_date', 'June 12, 2027', '2027-06-12', 'smoke-doc-1', "
            "'Warranty expires June 12, 2027.')"
        )
        parameters = json.dumps(
            {"title": "Renew warranty expires June 12, 2027",
             "due_date": "2027-05-13"}
        )
        for index in (1, 2, 3):
            conn.execute(
                "INSERT OR REPLACE INTO proposals (id, tool, parameters, "
                "rationale, evidence_document_hashes, status, tier) VALUES "
                "(?, 'create_reminder', ?, 'smoke test', ?, 'pending', 'review')",
                (f"smoke-proposal-{index}", parameters, json.dumps(["smoke-doc-1"])),
            )
    finally:
        conn.close()


def main() -> int:
    db_path = get_config().database_path
    if Path(db_path).exists():
        Path(db_path).unlink()

    try:
        from db.init_db import init_db

        init_db(db_path)
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: could not initialize the database: {exc}")
        return 1

    try:
        from api.main import create_app

        app = create_app()
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: the API failed to start: {exc}")
        return 1

    client = TestClient(app)

    print("Running LifeVault S1 smoke test...\n")

    check(client, "GET", "/api/health")

    check(client, "GET", "/api/roots")
    check(client, "POST", "/api/roots", 201, {"path": "/tmp/smoke-root", "exclude_patterns": []})
    check(client, "DELETE", "/api/roots/1")

    check(client, "POST", "/api/index/pause")
    check(client, "POST", "/api/index/resume")
    check(client, "GET", "/api/index/status")
    check(client, "POST", "/api/index/start", json_body={})

    check(client, "POST", "/api/chat", 200, {"message": "hello from smoke test"})

    # S4: documents are real, looked up by content_hash, so an unindexed
    # hash correctly 404s -- seed one row to exercise the "found" path too.
    check(client, "GET", "/api/documents/deadbeef", 404)
    from db.connect import connect as _connect

    _conn = _connect(db_path)
    try:
        _conn.execute(
            "INSERT OR IGNORE INTO documents (content_hash, title, doc_type, page_count) "
            "VALUES ('smoke-doc-1', 'Smoke Test Doc.pdf', 'pdf', 1)"
        )
        _conn.execute(
            "INSERT OR IGNORE INTO chunks (content_hash, chunk_index, text, page) "
            "VALUES ('smoke-doc-1', 0, 'Smoke test extracted text.', 1)"
        )
    finally:
        _conn.close()
    check(client, "GET", "/api/documents/smoke-doc-1")
    check(client, "GET", "/api/documents/smoke-doc-1/preview")
    check(client, "POST", "/api/documents/smoke-doc-1/open", 200, {})
    check(client, "POST", "/api/documents/smoke-doc-1/reveal")

    # S6/S7: /api/facts and /api/approvals are backed by real tables now, so
    # a fact and a proposal have to exist before they can be patched or
    # decided. Seeding them here keeps the smoke test end-to-end rather than
    # asserting the old fixture behavior.
    _seed_fact_and_proposal()

    check(client, "GET", "/api/facts")
    check(client, "GET", "/api/facts?type=warranty&expiring_within=60")
    check(client, "PATCH", "/api/facts/1", 200, {"user_corrected": True})

    check(client, "GET", "/api/approvals?status=pending")
    check(client, "POST", "/api/approvals/smoke-proposal-1", 200, {"decision": "approve"})
    check(client, "POST", "/api/approvals/smoke-proposal-2", 200,
          {"decision": "edit", "parameters": {"due_date": "2027-04-01"}})
    check(client, "POST", "/api/approvals/smoke-proposal-3", 200, {"decision": "reject"})

    check(client, "GET", "/api/memory")

    check(client, "GET", "/api/audit")
    check(client, "GET", "/api/audit/verify")

    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r[2])

    print(f"\n{passed}/{total} endpoint checks passed")

    if passed != total:
        print("\nFAILED checks:")
        for method, path, ok, detail in RESULTS:
            if not ok:
                print(f"  - {method} {path}: {detail}")
        return 1

    print("Smoke test PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
