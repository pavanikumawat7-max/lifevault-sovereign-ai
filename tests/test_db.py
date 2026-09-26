import sqlite3
import struct

import pytest


def test_db_initializes_all_required_tables(tmp_db_path):
    from db.connect import connect
    from db.init_db import init_db

    init_db(tmp_db_path)
    conn = connect(tmp_db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    for expected in [
        "index_roots",
        "documents",
        "file_locations",
        "chunks",
        "facts",
        "proposals",
        "memory",
        "audit_log",
    ]:
        assert expected in tables, f"missing table: {expected}"
    conn.close()


def test_wal_mode_enabled(fresh_conn):
    cur = fresh_conn.cursor()
    cur.execute("PRAGMA journal_mode")
    assert cur.fetchone()[0].lower() == "wal"


def test_foreign_keys_enabled(fresh_conn):
    cur = fresh_conn.cursor()
    cur.execute("PRAGMA foreign_keys")
    assert cur.fetchone()[0] == 1


def test_fts5_search_works(fresh_conn):
    cur = fresh_conn.cursor()
    cur.execute("INSERT INTO documents (content_hash, title) VALUES ('h1', 'Doc One')")
    cur.execute(
        "INSERT INTO chunks (content_hash, chunk_index, text) VALUES "
        "('h1', 0, 'a very findable sentence about vaccines')"
    )
    fresh_conn.commit()
    cur.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'findable'")
    assert len(cur.fetchall()) == 1


def test_init_db_is_idempotent(tmp_db_path):
    from db.init_db import init_db

    init_db(tmp_db_path)
    init_db(tmp_db_path)  # must not raise


def test_sqlite_vec_is_available_on_subsequent_connections(tmp_db_path):
    sqlite_vec = pytest.importorskip("sqlite_vec")
    probe = sqlite3.connect(":memory:")
    if not hasattr(probe, "enable_load_extension"):
        probe.close()
        pytest.skip("SQLite loadable extensions are unavailable")
    try:
        probe.enable_load_extension(True)
        sqlite_vec.load(probe)
    except sqlite3.Error:
        pytest.skip("sqlite-vec cannot load in this environment")
    finally:
        probe.close()

    from config import get_config
    from db.connect import connect
    from db.init_db import init_db

    init_db(tmp_db_path)
    conn = connect(tmp_db_path)
    try:
        dimension = get_config().embedding_dimension
        embedding = struct.pack(f"<{dimension}f", *([0.0] * dimension))
        conn.execute(
            "INSERT INTO chunks_vec (chunk_id, embedding) VALUES (?, ?)",
            (1, embedding),
        )
        assert conn.execute("SELECT COUNT(*) FROM chunks_vec").fetchone()[0] == 1
    finally:
        conn.close()
