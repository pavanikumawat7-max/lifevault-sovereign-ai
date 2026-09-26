"""Typed state shared across all 8 graph nodes.

`total=False` because any given run only populates the fields relevant to
where it currently is in the graph (e.g. `proposal` stays absent for a
pure Q&A turn with no action to propose). Later sessions should extend
this TypedDict with new optional keys rather than repurposing existing
ones -- node stubs in graph/nodes.py, and the routing functions in
graph/graph.py, both depend on the field names below.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

PolicyDecision = Literal["allow", "needs_approval", "deny"]
ApprovalStatus = Literal["pending", "approved", "denied"]


class LifeVaultState(TypedDict, total=False):
    # Input
    conversation_id: str
    user_message: str
    history: List[Dict[str, str]]

    # retrieve
    retrieved_chunks: List[Dict[str, Any]]

    # answer
    answer_text: str

    # verify_grounding
    grounded: bool
    citations: List[Dict[str, Any]]

    # propose_action
    proposal: Optional[Dict[str, Any]]

    # policy_check
    policy_decision: Optional[PolicyDecision]

    # human_approval
    approval_status: Optional[ApprovalStatus]

    # execute
    execution_result: Optional[Dict[str, Any]]

    # audit_and_memory
    audit_events: List[Dict[str, Any]]

    # error channel any node can set; downstream nodes should check it
    error: Optional[str]
