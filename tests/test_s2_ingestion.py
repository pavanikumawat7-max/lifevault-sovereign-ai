import os
import shutil
import stat
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")


def _pdf(path: Path, pages: list[str]) -> None:
    document = pymupdf.open()
    for content in pages:
        page = document.new_page()
        page.insert_text((72, 72), content)
    document.save(path)
    document.close()


def _configure(tmp_db_path, monkeypatch):
    monkeypatch.setenv("LIFEVAULT_DB_PATH", tmp_db_path)
    monkeypatch.setenv("LIFEVAULT_USE_FIXTURES", "true")
    from config import reset_config_cache

    reset_config_cache()
    from db.init_db import init_db

    init_db(tmp_db_path)


def test_normal_pdf_creates_page_chunks_fts_and_embeddings(
    tmp_path, tmp_db_path, monkeypatch
):
    _configure(tmp_db_path, monkeypatch)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _pdf(
        corpus / "warranty.pdf",
        [
            "Dell warranty begins today " + "coverage " * 520,
            "Warranty expires June 12 2027 " + "support " * 80,
        ],
    )

    from worker.index import approve_root, ingest_root
    from db.connect import connect

    result = ingest_root(approve_root(corpus, db_path=tmp_db_path), tmp_db_path)
    assert result["processed"] == 1
    assert result["chunks"] >= 2

    conn = connect(tmp_db_path)
    rows = conn.execute(
        "SELECT page, chunk_index FROM chunks ORDER BY chunk_index"
    ).fetchall()
    assert {row["page"] for row in rows} == {1, 2}
    assert conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == len(rows)
    if result["vectors"]:
        assert conn.execute("SELECT COUNT(*) FROM chunks_vec").fetchone()[0] == len(rows)
    conn.close()


def test_chunking_targets_500_tokens_with_60_token_overlap():
    from worker.chunk import chunk_pages
    from worker.parse import ParsedPage

    tokens = [f"token-{index}" for index in range(700)]
    chunks = chunk_pages([ParsedPage(page=7, text=" ".join(tokens))])
    assert len(chunks) == 2
    assert chunks[0].page == chunks[1].page == 7
    assert chunks[0].text.split()[-60:] == chunks[1].text.split()[:60]


def test_duplicate_content_has_one_document_and_two_locations(
    tmp_path, tmp_db_path, monkeypatch
):
    _configure(tmp_db_path, monkeypatch)
    corpus = tmp_path / "corpus"
    (corpus / "a").mkdir(parents=True)
    (corpus / "b").mkdir()
    _pdf(corpus / "a" / "invoice.pdf", ["Synthetic invoice INV-42"])
    shutil.copy2(corpus / "a" / "invoice.pdf", corpus / "b" / "copy.pdf")

    from worker.index import approve_root, ingest_root
    from db.connect import connect

    result = ingest_root(approve_root(corpus, db_path=tmp_db_path), tmp_db_path)
    conn = connect(tmp_db_path)
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM file_locations").fetchone()[0] == 2
    assert result["duplicates"] == 1
    conn.close()


def test_unchanged_file_prefilter_avoids_rehash(
    tmp_path, tmp_db_path, monkeypatch
):
    _configure(tmp_db_path, monkeypatch)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _pdf(corpus / "stable.pdf", ["Stable source"])

    from worker.index import approve_root, ingest_root
    import worker.scanner as scanner

    root_id = approve_root(corpus, db_path=tmp_db_path)
    ingest_root(root_id, tmp_db_path)

    def unexpected_hash(_path):
        raise AssertionError("unchanged file should not be hashed")

    monkeypatch.setattr(scanner, "_sha256", unexpected_hash)
    result = ingest_root(root_id, tmp_db_path)
    assert result["processed"] == 0


def test_incomplete_and_large_files_are_skipped(tmp_path, tmp_db_path, monkeypatch):
    _configure(tmp_db_path, monkeypatch)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "download.pdf.part").write_bytes(b"incomplete")
    with (corpus / "large.pdf").open("wb") as target:
        target.truncate(51 * 1024 * 1024)

    from worker.index import approve_root, ingest_root

    result = ingest_root(approve_root(corpus, db_path=tmp_db_path), tmp_db_path)
    assert result["found"] == 2
    assert result["skipped"] == 2
    assert result["processed"] == 0


def test_source_is_never_modified(tmp_path, tmp_db_path, monkeypatch):
    _configure(tmp_db_path, monkeypatch)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    source = corpus / "readonly.pdf"
    _pdf(source, ["Read only source document"])
    source.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    before = (source.read_bytes(), source.stat().st_mtime_ns, source.stat().st_mode)

    from worker.index import approve_root, ingest_root

    ingest_root(approve_root(corpus, db_path=tmp_db_path), tmp_db_path)
    after = (source.read_bytes(), source.stat().st_mtime_ns, source.stat().st_mode)
    assert after == before


def test_index_status_and_root_purge(tmp_path, tmp_db_path, monkeypatch):
    _configure(tmp_db_path, monkeypatch)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _pdf(corpus / "doc.pdf", ["Status test content"])

    from fastapi.testclient import TestClient
    from api.main import create_app
    from worker.index import approve_root, ingest_root

    root_id = approve_root(corpus, db_path=tmp_db_path)
    ingest_root(root_id, tmp_db_path)
    with TestClient(create_app()) as client:
        status_body = client.get("/api/index/status").json()["status"]
        assert status_body["documents_indexed"] == 1
        assert status_body["chunks_indexed"] == 1
        assert status_body["last_run_at"]
        assert client.post("/api/index/pause").json()["status"]["state"] == "paused"
        assert client.post("/api/index/resume").json()["status"]["state"] == "idle"
        assert client.delete(f"/api/roots/{root_id}").status_code == 200
        assert client.get("/api/index/status").json()["status"]["documents_indexed"] == 0
    from db.connect import connect

    conn = connect(tmp_db_path)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='chunks_vec'").fetchone():
        assert conn.execute("SELECT COUNT(*) FROM chunks_vec").fetchone()[0] == 0
    conn.close()


def test_root_delete_preserves_shared_document(
    tmp_path, tmp_db_path, monkeypatch
):
    _configure(tmp_db_path, monkeypatch)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _pdf(first / "shared.pdf", ["Shared synthetic content"])
    shutil.copy2(first / "shared.pdf", second / "shared.pdf")

    from worker.index import approve_root, ingest_root
    from db.connect import connect
    from api.routes.roots import delete_root

    first_id = approve_root(first, db_path=tmp_db_path)
    second_id = approve_root(second, db_path=tmp_db_path)
    ingest_root(first_id, tmp_db_path)
    ingest_root(second_id, tmp_db_path)
    delete_root(first_id)

    conn = connect(tmp_db_path)
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM file_locations").fetchone()[0] == 1
    conn.close()