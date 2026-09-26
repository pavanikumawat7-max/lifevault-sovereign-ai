"""SQLite connection helper.

`connect()` is the single place that knows how to open a LifeVault SQLite
connection correctly: WAL journal mode, foreign keys on, a sensible busy
timeout, and a Row row_factory for convenient column access. Every module
that touches the database should go through this helper rather than
calling `sqlite3.connect` directly.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from config import get_config

BUSY_TIMEOUT_MS = 5000
CONNECT_TIMEOUT_S = 30.0


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open (and lightly configure) a SQLite connection.

    Does NOT run the schema -- call `db.init_db.init_db()` first (or let
    callers that need a guaranteed-initialized DB do so explicitly). This
    keeps `connect()` cheap and side-effect-free beyond opening the file.
    """
    cfg = get_config()
    path = db_path or cfg.database_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    # isolation_level=None => autocommit; callers that need a transaction
    # (e.g. the audit hash chain) issue explicit BEGIN/COMMIT/ROLLBACK.
    conn = sqlite3.connect(path, timeout=CONNECT_TIMEOUT_S, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    _load_sqlite_vec(conn)
    return conn


def _load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """Register vec0 on this connection when the optional extension is usable."""
    enable_extensions = getattr(conn, "enable_load_extension", None)
    if enable_extensions is None:
        return False
    try:
        enable_extensions(True)
        try:
            try:
                import sqlite_vec
            except ImportError:
                conn.load_extension("vec0")
            else:
                sqlite_vec.load(conn)
        finally:
            enable_extensions(False)
        return True
    except (AttributeError, sqlite3.Error):
        return False
