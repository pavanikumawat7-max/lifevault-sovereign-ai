"""POST /api/approvals/{proposal_id} -- approve, edit or reject (S7).

This endpoint is what resumes a paused graph run. The sequence, and why each
step is in this order:

  1. Load the proposal row. It carries `thread_id`, so the pending run can be
     found even though this request may be handled by a process that has no
     memory of it -- which is exactly what makes approval survive an API
     restart.
  2. For `edit`, merge the human's parameters and re-run the policy gate. An
     edit is re-validated from scratch: a person changing a field is not a
     reason to trust the new value.
  3. Record the decision on the row, inside a transaction that refuses to
     decide an already-decided proposal. That is what makes a double-click,
     or a replayed request, safe.
  4. Resume the graph: write the decision into the thread's state, then
     invoke with `None` so execution continues from `human_approval` through
     `execute` and `audit_and_memory`.
  5. If the graph cannot be resumed (a checkpoint from a previous process
     that used an in-memory saver, say), fall back to executing and auditing
     directly. The user's decision must not be lost because of a
     checkpointing detail, and the audit row is written either way.

Also exposed, additively: `GET /api/approvals` to list proposals, which the
S8 approval card needs and no frozen contract covered.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from api.schemas import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ListProposalsResponse,
    Proposal,
)
from config import get_config
from graph import approval as approval_module

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

#: "deny" is the S1 wording, "reject" the handover plan's. Same outcome.
_REJECT_WORDS = {"reject", "deny"}


def _to_model(record: Dict[str, Any], untrusted: Optional[List[str]] = None) -> Proposal:
    return Proposal(
        id=str(record.get("id")),
        tool=str(record.get("tool") or ""),
        parameters=record.get("parameters") or {},
        rationale=record.get("rationale"),
        evidence_document_hashes=list(record.get("evidence_document_hashes") or []),
        status=str(record.get("status") or "pending"),
        decision=record.get("decision"),
        tier=record.get("tier"),
        untrusted_fields=list(untrusted or []),
        thread_id=record.get("thread_id"),
        created_at=record.get("created_at"),
        decided_at=record.get("decided_at"),
    )


@router.get("", response_model=ListProposalsResponse)
def list_proposals(
    status: Optional[str] = Query(None, description="pending|approved|denied|executed|error"),
    limit: int = Query(50, ge=1, le=200),
) -> ListProposalsResponse:
    """S7 additive endpoint: proposals for the approval queue."""
    records = approval_module.list_proposals(status=status, limit=limit)
    return ListProposalsResponse(proposals=[_to_model(r) for r in records])


@router.post("/{proposal_id}", response_model=ApprovalDecisionResponse)
def decide_approval(
    proposal_id: str, req: ApprovalDecisionRequest
) -> ApprovalDecisionResponse:
    try:
        proposal = approval_module.load_proposal(proposal_id)
    except approval_module.ProposalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    rejected = req.decision in _REJECT_WORDS
    edited_parameters: Optional[Dict[str, Any]] = None
    edit_diff: Optional[Dict[str, Any]] = None

    if req.decision == "edit":
        if not req.parameters:
            raise HTTPException(
                status_code=400,
                detail='decision="edit" requires a "parameters" object',
            )
        try:
            edited_parameters, edit_diff = approval_module.apply_edit(
                proposal, req.parameters
            )
        except approval_module.ApprovalError as exc:
            # A rejected edit leaves the proposal pending on purpose: the
            # human can correct their input and try again.
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    status = "denied" if rejected else "approved"
    try:
        updated = approval_module.record_decision(
            proposal_id,
            status=status,
            note=req.note,
            parameters=edited_parameters,
            edit_diff=edit_diff,
            db_path=None,
        )
    except approval_module.ProposalAlreadyDecided as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except approval_module.ProposalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    outcome = _resume_or_execute(updated, status)

    final = approval_module.load_proposal(proposal_id)
    return ApprovalDecisionResponse(
        proposal=_to_model(final),
        executed=bool(outcome.get("executed")),
        result=outcome.get("result"),
        edit_diff=edit_diff or (final.get("edit_diff") or None),
        audit_events=outcome.get("audit_events") or [],
        message=outcome.get("message"),
    )


def _resume_or_execute(proposal: Dict[str, Any], status: str) -> Dict[str, Any]:
    """Continue the paused graph run, or do the same work directly."""
    thread_id = proposal.get("thread_id")
    if thread_id:
        try:
            return _resume_graph(thread_id, proposal, status)
        except Exception as exc:  # noqa: BLE001 - documented fallback below
            logger.warning(
                "could not resume thread %s (%s); executing directly",
                thread_id, exc,
            )
    return _execute_directly(proposal, status)


def _resume_graph(
    thread_id: str, proposal: Dict[str, Any], status: str
) -> Dict[str, Any]:
    """Write the decision into the checkpointed thread and continue it."""
    from api.routes.chat import compiled_graph

    graph = compiled_graph(get_config().database_path)
    config = {"configurable": {"thread_id": thread_id}}

    snapshot = graph.get_state(config)
    if snapshot is None or not snapshot.next:
        raise RuntimeError("no paused checkpoint for this thread")

    graph.update_state(
        config,
        {
            "approval_status": status,
            "proposal": {**(snapshot.values.get("proposal") or {}), **proposal},
        },
    )
    final_state = graph.invoke(None, config=config)
    result = final_state.get("execution_result") or {}
    return {
        "executed": bool(result.get("executed")),
        "result": result or None,
        "audit_events": final_state.get("audit_events") or [],
        "message": None if result.get("ok", True) else result.get("reason"),
    }


def _execute_directly(proposal: Dict[str, Any], status: str) -> Dict[str, Any]:
    """Fallback path: run the tool and write the audit rows without the graph.

    Reached when there is no resumable checkpoint -- for instance a proposal
    created by a process that fell back to an in-memory checkpointer. The
    decision, the execution and the audit rows all still happen, so the
    observable behavior matches the graph path.
    """
    from graph.audit_memory import audit_and_memory
    from graph.execute import execute_proposal

    result: Optional[Dict[str, Any]] = None
    if status == "approved":
        result = execute_proposal(str(proposal["id"]))

    state = {
        "conversation_id": proposal.get("thread_id"),
        "user_message": None,
        "grounded": True,
        "citations": [],
        "proposal": proposal,
        "policy_decision": "needs_approval",
        "approval_status": status,
        "execution_result": result,
        "audit_events": [],
    }
    audited = audit_and_memory(state)
    return {
        "executed": bool(result and result.get("executed")),
        "result": result,
        "audit_events": audited.get("audit_events") or [],
        "message": None if not result or result.get("ok", True) else result.get("reason"),
    }
