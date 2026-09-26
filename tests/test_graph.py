import pytest

pytest.importorskip("langgraph")


def test_graph_builds_and_runs_end_to_end(tmp_db_path, monkeypatch):
    monkeypatch.setenv("LIFEVAULT_DB_PATH", tmp_db_path)
    from config import reset_config_cache

    reset_config_cache()

    from langgraph.checkpoint.memory import MemorySaver

    from graph.graph import build_graph

    app = build_graph(checkpointer=MemorySaver())
    run_config = {"configurable": {"thread_id": "test-thread-1"}}

    result = app.invoke(
        {"conversation_id": "c1", "user_message": "hi", "history": []},
        config=run_config,
    )

    # Every node ran node-to-node without a proposal, so the graph should
    # have taken the "no proposal -> straight to audit_and_memory" path.
    assert result["answer_text"]
    assert result["grounded"] is False
    assert result["proposal"] is None
    assert result["policy_decision"] is None
    assert result["execution_result"] is None
    assert "audit_events" in result


def test_route_after_policy_no_proposal_skips_approval():
    from graph.graph import route_after_policy

    assert route_after_policy({"policy_decision": None}) == "audit_and_memory"
    assert route_after_policy({"policy_decision": "deny"}) == "audit_and_memory"
    assert route_after_policy({"policy_decision": "needs_approval"}) == "human_approval"


def test_route_after_approval_only_approved_executes():
    from graph.graph import route_after_approval

    assert route_after_approval({"approval_status": "approved"}) == "execute"
    assert route_after_approval({"approval_status": "denied"}) == "audit_and_memory"
    assert route_after_approval({"approval_status": "pending"}) == "audit_and_memory"
    assert route_after_approval({"approval_status": None}) == "audit_and_memory"
