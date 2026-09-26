import json

from api.audit import GENESIS_HASH, AuditLog


def test_first_audit_row(fresh_conn):
    audit = AuditLog(fresh_conn)
    row = audit.log("test.first", {"a": 1})
    assert row["prev_hash"] == GENESIS_HASH
    assert row["id"] == 1
    assert len(row["row_hash"]) == 64


def test_chained_second_row(fresh_conn):
    audit = AuditLog(fresh_conn)
    row1 = audit.log("first", {"n": 1})
    row2 = audit.log("second", {"n": 2})
    assert row2["prev_hash"] == row1["row_hash"]
    assert row2["row_hash"] != row1["row_hash"]


def test_verify_success(fresh_conn):
    audit = AuditLog(fresh_conn)
    audit.log("a", {"x": 1})
    audit.log("b", {"x": 2})
    audit.log("c", {"x": 3})
    result = audit.verify()
    assert result["valid"] is True
    assert result["rows_checked"] == 3
    assert result["reason"] is None


def test_verify_empty_log_is_valid(fresh_conn):
    result = AuditLog(fresh_conn).verify()
    assert result == {"valid": True, "reason": None, "row_id": None, "rows_checked": 0}


def test_verify_detects_payload_tampering(fresh_conn):
    audit = AuditLog(fresh_conn)
    audit.log("a", {"x": 1})
    audit.log("b", {"x": 2})

    cur = fresh_conn.cursor()
    cur.execute("UPDATE audit_log SET payload = ? WHERE id = 1", (json.dumps({"x": 999}),))
    fresh_conn.commit()

    result = audit.verify()
    assert result["valid"] is False
    assert result["row_id"] == 1
    assert result["reason"] == "row_hash_mismatch"


def test_verify_detects_chain_tampering(fresh_conn):
    audit = AuditLog(fresh_conn)
    audit.log("a", {"x": 1})
    audit.log("b", {"x": 2})

    cur = fresh_conn.cursor()
    cur.execute("UPDATE audit_log SET prev_hash = ? WHERE id = 2", ("f" * 64,))
    fresh_conn.commit()

    result = audit.verify()
    assert result["valid"] is False
    assert result["row_id"] == 2


def test_list_recent_returns_newest_first(fresh_conn):
    audit = AuditLog(fresh_conn)
    audit.log("a", {})
    audit.log("b", {})
    entries = audit.list_recent(limit=10)
    assert [e["event"] for e in entries] == ["b", "a"]
