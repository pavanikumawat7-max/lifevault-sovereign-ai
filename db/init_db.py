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
        _apply_s2_migrations(conn)
        _apply_s7_migrations(conn)
        _init_vector_table(conn, cfg.embedding_dimension)
    finally:
        conn.close()


def _apply_s2_migrations(conn: sqlite3.Connection) -> None:
    """Add S2 prefilter columns to databases created from the frozen S1 schema."""
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(file_locations)")
    }
    if "size_bytes" not in columns:
        conn.execute("ALTER TABLE file_locations ADD COLUMN size_bytes INTEGER")
    if "mtime_ns" not in columns:
        conn.execute("ALTER TABLE file_locations ADD COLUMN mtime_ns INTEGER")


def _apply_s7_migrations(conn: sqlite3.Connection) -> None:
    """Additive S7 storage: a reminders table and three proposal columns.

    All additive, per the frozen-contract rule -- nothing existing is
    renamed, dropped or retyped, and every statement is safe to re-run.

    * `reminders` did not exist in the S1 schema even though the handover
      plan says create_reminder writes a reminders row, so it is added here.
    * `proposals.thread_id` is what makes approval survive an API restart:
      it records which LangGraph thread to resume, so the decision can
      arrive in a completely different process.
    * `proposals.edit_diff` and `proposals.tier` record what a human changed
      and how sensitive the action was, both required in the audit row.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(proposals)")}
    for name, ddl in (
        ("thread_id", "ALTER TABLE proposals ADD COLUMN thread_id TEXT"),
        ("edit_diff", "ALTER TABLE proposals ADD COLUMN edit_diff TEXT"),
        ("tier", "ALTER TABLE proposals ADD COLUMN tier TEXT"),
    ):
        if name not in columns:
            conn.execute(ddl)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            title         TEXT NOT NULL,
            due_date      TEXT NOT NULL,          -- ISO-8601 date
            notes         TEXT,
            ics_path      TEXT,                   -- .ics file written in the vault
            proposal_id   TEXT REFERENCES proposals(id) ON DELETE SET NULL,
            source_document_hash TEXT REFERENCES documents(content_hash) ON DELETE SET NULL,
            created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reminders_due_date ON reminders(due_date)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_proposals_thread_id ON proposals(thread_id)"
    )


def _init_vector_table(conn: sqlite3.Connection, dimension: int) -> None:
    """Best-effort creation of the sqlite-vec virtual table.

    sqlite-vec is a loadable SQLite extension, not always installed. S1
    must not hard-fail if it's missing -- everything else in the schema
    (documents, chunks, FTS5 search, audit_log, ...) still works without
    it. Later sessions that add real embeddings should call this again
    (it's idempotent) once the extension is confirmed available.
    """
    try:
        try:
            import sqlite_vec

            conn.enable_load_extension(True)
            try:
                sqlite_vec.load(conn)
            finally:
                conn.enable_load_extension(False)
        except ImportError:
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
