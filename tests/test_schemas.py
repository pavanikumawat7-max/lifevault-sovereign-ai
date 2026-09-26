import pytest

pytest.importorskip("pydantic")


def test_schemas_module_has_expected_models():
    from api import schemas

    for name in [
        "IndexRoot",
        "ListRootsResponse",
        "ChatRequest",
        "ChatResponse",
        "DocumentSummary",
        "Fact",
        "Proposal",
        "MemoryEntry",
        "AuditEntry",
        "AuditVerifyResponse",
    ]:
        assert hasattr(schemas, name), f"missing schema: {name}"


def test_chat_request_defaults():
    from api.schemas import ChatRequest

    req = ChatRequest(message="hello")
    assert req.message == "hello"
    assert req.history == []
    assert req.conversation_id is None


def test_index_root_round_trip():
    from api.schemas import IndexRoot

    root = IndexRoot(id=1, path="/tmp", exclude_patterns=["*.tmp"])
    data = root.model_dump()
    assert data["path"] == "/tmp"
    rebuilt = IndexRoot(**data)
    assert rebuilt == root


def test_audit_verify_response_shape():
    from api.schemas import AuditVerifyResponse

    resp = AuditVerifyResponse(valid=True, reason=None, row_id=None, rows_checked=0)
    assert resp.valid is True
