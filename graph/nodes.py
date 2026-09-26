"""The 8 LifeVault graph nodes, as typed stubs.

Node functions take the current LifeVaultState and return a partial dict
of updates (the LangGraph convention for StateGraph node functions), so
each node only needs to know about the keys it actually touches.

None of these implement real retrieval, answering, grounding checks,
proposal generation, policy decisions, execution, or memory writes --
that is explicitly out of scope for S1. What IS locked in here is the
*shape* of each node's output, and two behaviors later sessions must
preserve (see graph/graph.py's routing functions):

  1. A "deny" policy decision, or no proposal at all, routes straight to
     audit_and_memory (skipping human_approval and execute).
  2. human_approval is where a later session wires a real LangGraph
     interrupt; resuming the graph after a human decides is what moves
     approval_status from "pending" to "approved"/"denied".
"""
from __future__ import annotations

from graph.state import LifeVaultState


def retrieve(state: LifeVaultState) -> dict:
    """..."""
    return {"retrieved_chunks": [], "execution_result": None}


def answer(state: LifeVaultState) -> dict:
    """S1 stub: no real answer generation. See llm.py for the (fixture-
    mode-capable) chat wrapper a later session will call from here."""
    return {
        "answer_text": "[stub] no real answer generation in S1",
        "citations": [],
    }


def verify_grounding(state: LifeVaultState) -> dict:
    """S1 stub: grounding is never verified, so `grounded` defaults to
    False rather than being (falsely) asserted True."""
    return {"grounded": False}


def propose_action(state: LifeVaultState) -> dict:
    """S1 stub: no proposals are ever generated."""
    return {"proposal": None}


def policy_check(state: LifeVaultState) -> dict:
    """S1 stub: with no proposal there is nothing to evaluate, so the
    decision is None (graph/graph.py routes None the same as "deny")."""
    if state.get("proposal") is None:
        return {"policy_decision": None}
    return {"policy_decision": "needs_approval"}


def human_approval(state: LifeVaultState) -> dict:
    """S1 stub: interrupt PLACEHOLDER only.

    A later session should replace the body of this node with a real
    LangGraph interrupt (e.g. `langgraph.types.interrupt(...)`) that
    pauses execution until POST /api/approvals/{proposal_id} resumes the
    graph with the human's decision. For S1, if there's no proposal there
    is nothing to approve; otherwise the status is left "pending" and it
    is the caller's job to resume the graph later.
    """
    if state.get("proposal") is None:
        return {"approval_status": None}
    return {"approval_status": "pending"}


def execute(state: LifeVaultState) -> dict:
    """S1 stub: no tool is ever actually invoked. See tools/registry.py."""
    return {"execution_result": None}


def audit_and_memory(state: LifeVaultState) -> dict:
    """S1 stub: does not write to audit_log or memory yet. A later
    session should call api.audit.AuditLog.log(...) here and upsert a
    `memory` row reflecting the run's outcome."""
    return {"audit_events": list(state.get("audit_events") or [])}
