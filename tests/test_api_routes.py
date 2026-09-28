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


def test_index_start_with_no_roots(tmp_db_path, monkeypatch):
    client = _client(tmp_db_path, monkeypatch)
    resp = client.post("/api/index/start", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["started"] is False
    assert "no enabled" in body["message"].lower() or "grant a folder" in body["message"].lower()


def test_index_start_unknown_root_404(tmp_db_path, monkeypatch):
    client = _client(tmp_db_path, monkeypatch)
    resp = client.post("/api/index/start", json={"root_id": 999})
    assert resp.status_code == 404


def test_index_start_paused_root_400(tmp_db_path, monkeypatch, tmp_path):
    client = _client(tmp_db_path, monkeypatch)
    created = client.post(
        "/api/roots", json={"path": str(tmp_path), "exclude_patterns": []}
    ).json()["root"]
    client.post("/api/index/pause")
    resp = client.post("/api/index/start", json={"root_id": created["id"]})
    assert resp.status_code == 400


def test_index_start_real_root_scans_in_background(tmp_db_path, monkeypatch, tmp_path):
    import time

    client = _client(tmp_db_path, monkeypatch)
    created = client.post(
        "/api/roots", json={"path": str(tmp_path), "exclude_patterns": []}
    ).json()["root"]

    resp = client.post("/api/index/start", json={"root_id": created["id"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["started"] is True
    assert body["roots_queued"] == [created["id"]]
    # The state flips to "scanning"/"indexing" immediately, then the
    # background thread finishes (the folder is empty, so no PDFs to
    # parse/embed) and settles back to "idle" -- confirms the whole
    # grant -> auto-index -> status flow works without a manual script.
    for _ in range(50):
        status = client.get("/api/index/status").json()["status"]
        if status["state"] == "idle":
            break
        time.sleep(0.05)
    assert status["state"] == "idle"


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
    """S6 made /api/facts real, so a fact has to exist to be listed.

    An empty facts table now correctly returns an empty list instead of the
    S1 fixture, which is what this test used to rely on.
    """
    client = _client(tmp_db_path, monkeypatch)

    assert client.get("/api/facts").json()["facts"] == []

    from db.connect import connect

    conn = connect(tmp_db_path)
    try:
        conn.execute(
            "INSERT INTO facts (type, field, value, norm_value, source_quote) "
            "VALUES ('warranty', 'expiry_date', 'June 12, 2027', '2027-06-12', "
            "'Warranty expires June 12, 2027.')"
        )
    finally:
        conn.close()

    facts = client.get("/api/facts").json()["facts"]
    assert len(facts) == 1
    assert facts[0]["norm_value"] == "2027-06-12"
    assert facts[0]["label"] == "Expiry Date"

    fact_id = facts[0]["id"]
    resp2 = client.patch(f"/api/facts/{fact_id}", json={"user_corrected": True})
    assert resp2.status_code == 200
    assert resp2.json()["fact"]["user_corrected"] is True


def test_approvals_decision(tmp_db_path, monkeypatch, tmp_path):
    """S7 made this route real, so a proposal has to exist to be decided.

    Deciding an unknown id is now a 404 instead of mutating a fixture, which
    is what this test used to rely on.
    """
    monkeypatch.setenv("LIFEVAULT_VAULT_DIR", str(tmp_path / "vault"))
    client = _client(tmp_db_path, monkeypatch)

    assert client.post(
        "/api/approvals/stub-proposal-1", json={"decision": "approve"}
    ).status_code == 404

    from db.connect import connect

    conn = connect(tmp_db_path)
    try:
        conn.execute(
            "INSERT INTO documents (content_hash, title) VALUES ('h1', 'w.pdf')"
        )
        conn.execute(
            "INSERT INTO proposals (id, tool, parameters, rationale, "
            "evidence_document_hashes, status, tier) VALUES "
            "('p1', 'create_reminder', "
            "'{\"title\": \"Renew warranty\", \"due_date\": \"2027-05-13\"}', "
            "'because it expires', '[\"h1\"]', 'pending', 'review')"
        )
    finally:
        conn.close()

    resp = client.post("/api/approvals/p1", json={"decision": "approve"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["proposal"]["status"] == "executed"
    assert body["executed"] is True
    assert body["result"]["output"]["ics_path"].endswith(".ics")

    # Deciding it twice is a conflict, not a second execution.
    assert client.post(
        "/api/approvals/p1", json={"decision": "approve"}
    ).status_code == 409


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
