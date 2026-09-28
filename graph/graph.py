"""Builds the LifeVault LangGraph.

Topology (8 nodes, exactly as specified for S1):

    retrieve -> answer -> verify_grounding -> propose_action -> policy_check
        -> [human_approval | audit_and_memory]   (conditional, see below)
    human_approval -> [execute | audit_and_memory]  (conditional, see below)
    execute -> audit_and_memory -> END

Two routing rules are pinned for later sessions to preserve:

  * route_after_policy: a "deny" decision, or no proposal at all
    (policy_decision is None), skips human_approval entirely and goes
    straight to audit_and_memory. Only "needs_approval" (or "allow", if a
    later session decides some tools never need a human) reaches
    human_approval.
  * route_after_approval: only an "approved" outcome reaches execute;
    "denied" (and the S1 default "pending", since no real interrupt/resume
    exists yet) goes to audit_and_memory instead.

human_approval itself is only an interrupt PLACEHOLDER in S1 (see
graph/nodes.py) -- it does not actually pause the graph on a real
LangGraph interrupt yet. Wiring a real interrupt + resume-on-approval flow
belongs to a later session; this module's job is just to make sure the
graph *shape* already anticipates it.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from langgraph.graph import END, StateGraph

from config import get_config
from graph import nodes
from graph.state import LifeVaultState


def route_after_policy(state: LifeVaultState) -> str:
    decision = state.get("policy_decision")
    if decision in (None, "deny"):
        return "audit_and_memory"
    return "human_approval"


def route_after_approval(state: LifeVaultState) -> str:
    status = state.get("approval_status")
    if status == "approved":
        return "execute"
    return "audit_and_memory"


def _default_checkpointer():
    """Prefer a SQLite-backed checkpointer so graph runs survive process
    restarts; fall back to an in-memory one if the optional
    `langgraph-checkpoint-sqlite` package isn't installed or its API
    doesn't match what this LangGraph version expects."""
    cfg = get_config()
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        conn = sqlite3.connect(cfg.database_path, check_same_thread=False)
        return SqliteSaver(conn)
    except Exception as exc:  # noqa: BLE001 - deliberate, documented fallback
        print(
            "[graph.graph] SqliteSaver unavailable "
            f"({exc}); falling back to in-memory checkpointing. Install "
            "`langgraph-checkpoint-sqlite` for persistent checkpoints."
        )
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()


def build_graph(
    checkpointer: Optional[object] = None,
    interrupt_for_approval: bool = True,
):
    """Build and compile the LifeVault graph. Pass a checkpointer (e.g.
    `MemorySaver()`) explicitly in tests for a fast, dependency-free run;
    otherwise a SQLite-backed one is used when available.

    `interrupt_for_approval` (S7) compiles the graph with
    `interrupt_before=["human_approval"]`, which is what makes the approval
    gate real: a run that produces a proposal stops before that node and
    waits. Resume by writing the decision into the thread's state and
    invoking with `None` -- see graph/approval.py for the full sequence and
    why static interrupts are used instead of the dynamic `interrupt()`
    (LangGraph is pinned `<0.3`, where that function does not yet exist).

    Note this changes nothing for a turn with no proposal: routing sends
    those from policy_check straight to audit_and_memory, so `human_approval`
    is never entered and no pause happens. Pass False to compile a
    non-pausing graph for tests that want a single uninterrupted run.
    """
    graph = StateGraph(LifeVaultState)

    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("answer", nodes.answer)
    graph.add_node("verify_grounding", nodes.verify_grounding)
    graph.add_node("propose_action", nodes.propose_action)
    graph.add_node("policy_check", nodes.policy_check)
    graph.add_node("human_approval", nodes.human_approval)
    graph.add_node("execute", nodes.execute)
    graph.add_node("audit_and_memory", nodes.audit_and_memory)

    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", "verify_grounding")
    graph.add_edge("verify_grounding", "propose_action")
    graph.add_edge("propose_action", "policy_check")

    graph.add_conditional_edges(
        "policy_check",
        route_after_policy,
        {"human_approval": "human_approval", "audit_and_memory": "audit_and_memory"},
    )
    graph.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {"execute": "execute", "audit_and_memory": "audit_and_memory"},
    )

    graph.add_edge("execute", "audit_and_memory")
    graph.add_edge("audit_and_memory", END)

    if checkpointer is None:
        checkpointer = _default_checkpointer()

    compile_kwargs = {"checkpointer": checkpointer}
    if interrupt_for_approval:
        compile_kwargs["interrupt_before"] = ["human_approval"]
    return graph.compile(**compile_kwargs)
