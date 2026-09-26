import pytest

from worker.worker import IndexResult, ParseResult, ScanResult, Worker


def test_worker_scan_returns_contract(tmp_path, tmp_db_path):
    result = Worker(tmp_db_path).scan(str(tmp_path))
    assert isinstance(result, ScanResult)
    assert result.root_id > 0


def test_worker_parse_missing_document_is_clear(tmp_db_path):
    from db.init_db import init_db

    init_db(tmp_db_path)
    with pytest.raises(FileNotFoundError):
        Worker(tmp_db_path).parse("deadbeef")


def test_worker_index_empty_document_keeps_contract(tmp_db_path):
    from db.connect import connect
    from db.init_db import init_db

    init_db(tmp_db_path)
    conn = connect(tmp_db_path)
    conn.execute("INSERT INTO documents (content_hash, title) VALUES ('deadbeef', 'Empty')")
    conn.close()
    result = Worker(tmp_db_path).index("deadbeef")
    assert isinstance(result, IndexResult)
    assert result.chunks_indexed == 0
