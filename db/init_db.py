"""Database initialization / migration entry point.

Running this module (directly, or via `init_db()`) must leave a fresh
machine with a fully-usable SQLite database: all tables, the FTS5 index,
triggers, and indexes from schema.sql, plus (best-effort) a sqlite-vec
virtual table sized from the configured embedding dimension.

This is intentionally a plain "apply schema.sql, then do the one
dimension-dependent piece in Python" script rather than a full migration
framework -- S1 has nothing to migrate from yet. Later sessions can layer
versioned migrations on top without changing this entry point's contract:
`init_db(db_path=None) -> None` must keep working.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from config import get_config
from db.connect import connect

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def init_db(db_path: Optional[str] = None) -> None:
    """Create the database file (if needed) and apply the schema."""
    cfg = get_config()
    resolved_path = db_path or cfg.database_path
    conn = connect(resolved_path)
    try:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)
        _init_vector_table(conn, cfg.embedding_dimension)
    finally:
        conn.close()


def _init_vector_table(conn: sqlite3.Connection, dimension: int) -> None:
    """Best-effort creation of the sqlite-vec virtual table.

    sqlite-vec is a loadable SQLite extension, not always installed. S1
    must not hard-fail if it's missing -- everything else in the schema
    (documents, chunks, FTS5 search, audit_log, ...) still works without
    it. Later sessions that add real embeddings should call this again
    (it's idempotent) once the extension is confirmed available.
    """
    try:
        conn.enable_load_extension(True)
        try:
            conn.load_extension("vec0")
        finally:
            conn.enable_load_extension(False)
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0("
            "chunk_id INTEGER PRIMARY KEY, "
            f"embedding float[{int(dimension)}])"
        )
    except Exception as exc:  # noqa: BLE001 - deliberately broad, non-fatal
        print(
            "[db.init_db] sqlite-vec extension not available; skipping "
            f"chunks_vec table for now ({exc}). Vector search lands in a "
            "later session once the extension is installed."
        )


if __name__ == "__main__":
    init_db()
    print(f"[db.init_db] Database initialized at {get_config().database_path}")
