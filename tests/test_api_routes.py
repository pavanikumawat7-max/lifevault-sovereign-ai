import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")


def _client(tmp_db_path, monkeypatch):
    monkeypatch.setenv("LIFEVAULT_DB_PATH", tmp_db_path)
    monkeypatch.setenv("LIFEVAULT_USE_FIXTURES", "true")
    from config import reset_config_cache

    reset_config_cache()

    from db.init_db import init_db

    init_db(tmp_db_path)

    from api.main import create_app

    return fastapi_testclient.TestClient(create_app())


def test_health(tmp_db_path, monkeypatch):
    client = _client(tmp_db_path, monkeypatch)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_roots_list_and_create(tmp_db_path, monkeypatch):
    client = _client(tmp_db_path, monkeypatch)
    resp = client.get("/api/roots")
    assert resp.status_code == 200
    assert "roots" in resp.json()

    resp2 = client.post("/api/roots", json={"path": "/tmp/example", "exclude_patterns": []})
    assert resp2.status_code == 201
    assert resp2.json()["root"]["path"] == "/tmp/example"


def test_roots_delete(tmp_db_path, monkeypatch):
    client = _client(tmp_db_path, monkeypatch)
    resp = client.delete("/api/roots/1")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_index_pause_resume_status(tmp_db_path, monkeypatch):
    client = _client(tmp_db_path, monkeypatch)
    resp = client.post("/api/index/pause")
    assert resp.status_code == 200
    assert resp.json()["status"]["state"] == "paused"

    resp2 = client.post("/api/index/resume")
    assert resp2.status_code == 200
    assert resp2.json()["status"]["state"] == "idle"

    resp3 = client.get("/api/index/status")
    assert resp3.status_code == 200
    assert "state" in resp3.json()["status"]


def test_chat_returns_fixture_answer(tmp_db_path, monkeypatch):
    client = _client(tmp_db_path, monkeypatch)
    resp = client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"]
    assert body["conversation_id"]


def test_documents_endpoints_404_when_unknown(tmp_db_path, monkeypatch):
    # S4: documents are real, looked up by content_hash. An unindexed hash
    # is a 404, not fixture data -- the citation viewer needs to be able to
    # tell "not found" apart from "found, but empty".
    client = _client(tmp_db_path, monkeypatch)
    h = "deadbeef"
    assert client.get(f"/api/documents/{h}").status_code == 404
    assert client.get(f"/api/documents/{h}/preview").status_code == 404
    assert client.post(f"/api/documents/{h}/open", json={}).status_code == 404
    assert client.post(f"/api/documents/{h}/reveal").status_code == 404


def test_documents_endpoints_for_indexed_document(tmp_db_path, monkeypatch):
    client = _client(tmp_db_path, monkeypatch)
    from db.connect import connect

    conn = connect(tmp_db_path)
    try:
        h = "deadbeefcafebabe"
        conn.execute(
            "INSERT INTO documents (content_hash, title, doc_type, page_count) "
            "VALUES (?, 'Sample.pdf', 'pdf', 3)",
            (h,),
        )
        conn.execute(
            "INSERT INTO file_locations (content_hash, path) VALUES (?, ?)",
            (h, "/tmp/does-not-exist/Sample.pdf"),
        )
        conn.execute(
            "INSERT INTO chunks (content_hash, chunk_index, text, page) "
            "VALUES (?, 0, 'Some extracted text.', 1)",
            (h,),
        )
    finally:
        conn.close()

    detail = client.get(f"/api/documents/{h}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["document"]["title"] == "Sample.pdf"
    assert len(body["locations"]) == 1
    assert body["chunk_count"] == 1

    preview = client.get(f"/api/documents/{h}/preview")
    assert preview.status_code == 200
    assert "Some extracted text." in preview.json()["preview_text"]

    # The file doesn't exist on disk in this test, so open/reveal succeed
    # at the HTTP layer but report opened/revealed=False with a reason.
    opened = client.post(f"/api/documents/{h}/open", json={})
    assert opened.status_code == 200
    assert opened.json()["opened"] is False

    revealed = client.post(f"/api/documents/{h}/reveal")
    assert revealed.status_code == 200
    assert revealed.json()["revealed"] is False


def test_facts_list_and_patch(tmp_db_path, monkeypatch):
    client = _client(tmp_db_path, monkeypatch)
    resp = client.get("/api/facts")
    assert resp.status_code == 200
    facts = resp.json()["facts"]
    assert len(facts) >= 1

    fact_id = facts[0]["id"]
    resp2 = client.patch(f"/api/facts/{fact_id}", json={"user_corrected": True})
    assert resp2.status_code == 200
    assert resp2.json()["fact"]["user_corrected"] is True


def test_approvals_decision(tmp_db_path, monkeypatch):
    client = _client(tmp_db_path, monkeypatch)
    resp = client.post("/api/approvals/stub-proposal-1", json={"decision": "approve"})
    assert resp.status_code == 200
    assert resp.json()["proposal"]["status"] == "approved"


def test_memory_list(tmp_db_path, monkeypatch):
    client = _client(tmp_db_path, monkeypatch)
    resp = client.get("/api/memory")
    assert resp.status_code == 200
    assert "entries" in resp.json()


def test_audit_list_and_verify(tmp_db_path, monkeypatch):
    client = _client(tmp_db_path, monkeypatch)
    resp = client.get("/api/audit")
    assert resp.status_code == 200
    assert "entries" in resp.json()

    resp2 = client.get("/api/audit/verify")
    assert resp2.status_code == 200
    assert resp2.json()["valid"] is True
