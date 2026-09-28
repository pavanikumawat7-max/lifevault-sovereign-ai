"""The 8 LifeVault graph nodes.

Node functions take the current LifeVaultState and return a partial dict
of updates (the LangGraph convention for StateGraph node functions), so
each node only needs to know about the keys it actually touches.

S3 made the first three real. `retrieve`, `answer` and `verify_grounding`
are now thin re-exports of graph/retrieve.py, graph/answer.py and
graph/verify.py -- the implementations live in those modules so they can
be tested and driven by scripts/eval.py without building a graph, and so
this file stays the one place that lists what a node is.

`propose_action`, `policy_check`, `human_approval`, `execute` and
`audit_and_memory` are still S1 stubs, to be made real in S7. What IS
locked in here is the *shape* of each node's output, and two behaviors
later sessions must preserve (see graph/graph.py's routing functions):

  1. A "deny" policy decision, or no proposal at all, routes straight to
     audit_and_memory (skipping human_approval and execute).
  2. human_approval is where a later session wires a real LangGraph
     interrupt; resuming the graph after a human decides is what moves
     approval_status from "pending" to "approved"/"denied".
"""
from __future__ import annotations

from graph.answer import answer
from graph.approval import human_approval
from graph.audit_memory import audit_and_memory
from graph.execute import execute
from graph.propose import propose_action
from graph.retrieve import retrieve
from graph.state import LifeVaultState
from graph.verify import verify_grounding

__all__ = [
    "retrieve",
    "answer",
    "verify_grounding",
    "propose_action",
    "policy_check",
    "human_approval",
    "execute",
    "audit_and_memory",
]


def policy_check(state: LifeVaultState) -> dict:
    """S1 stub: with no proposal there is nothing to evaluate, so the
    decision is None (graph/graph.py routes None the same as "deny")."""
    if state.get("proposal") is None:
        return {"policy_decision": None}
    return {"policy_decision": "needs_approval"}


def policy_check(state: LifeVaultState) -> dict:
    """Evaluate the pending proposal against policy/policy.py (S7).

    Returns None (routed like "deny") when there is nothing to evaluate, so
    the S1 routing contract in graph/graph.py is unchanged: only
    "needs_approval" or "allow" ever reaches human_approval.
    """
    proposal = state.get("proposal")
    if not isinstance(proposal, dict):
        return {"policy_decision": None}

    from policy.policy import check_proposal

    verdict = check_proposal(
        tool=proposal.get("tool", ""),
        parameters=proposal.get("params") or proposal.get("parameters"),
        evidence_document_hashes=proposal.get("evidence_document_hashes"),
    )
    updated = dict(proposal)
    updated["policy"] = verdict.to_dict()
    updated["untrusted_fields"] = verdict.untrusted_fields
    return {"policy_decision": verdict.decision, "proposal": updated}
