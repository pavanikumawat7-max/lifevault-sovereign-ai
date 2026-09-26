"""Shared FastAPI dependencies."""
from __future__ import annotations

import sqlite3
from typing import Iterator

from db.connect import connect


def get_db() -> Iterator[sqlite3.Connection]:
    """Yield a per-request SQLite connection, always closed afterward."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
