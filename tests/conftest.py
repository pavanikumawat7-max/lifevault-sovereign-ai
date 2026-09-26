import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_db_path(tmp_path) -> str:
    return str(tmp_path / "test_lifevault.db")


@pytest.fixture
def fresh_conn(tmp_db_path):
    """A connection to a freshly-initialized temp DB, closed after the test."""
    from db.connect import connect
    from db.init_db import init_db

    init_db(tmp_db_path)
    conn = connect(tmp_db_path)
    yield conn
    conn.close()
