"""Human approval, and the interrupt/resume machinery behind it (S7).

The handover plan flags interrupt-and-resume across an API restart as the
top technical risk of this session, so here is exactly how it works.

LangGraph is pinned to `>=0.2,<0.3` in requirements.txt, and the dynamic
`interrupt()` function only arrives in 0.2.30+. Rather than bump a shared
dependency mid-project, this uses the **static interrupt** available in
0.2.x: the graph is compiled with `interrupt_before=["human_approval"]`.

The flow:

  1. `POST /api/chat` invokes the graph with `thread_id = conversation_id`.
  2. The graph runs retrieve -> answer -> verify -> propose -> policy_check
     and then **stops before** `human_approval`. The pending proposal is
     already written to the `proposals` table with that `thread_id`.
  3. The process can now die. The checkpoint lives in `data/lifevault.db`
     via SqliteSaver, and the proposal row records which thread to resume.
  4. `POST /api/approvals/{id}` looks the proposal up, writes the decision
     into the thread's state with `update_state`, and invokes the graph with
     `None` to continue from `human_approval` onward.

That is why step 4 works in a brand-new process: nothing about the pending
turn is held in memory.

`human_approval` itself is deliberately a near-no-op. By the time it runs,
the decision has already been written into state by the resume call; the
node's job is only to normalize it and let the routing function in
graph/graph.py do the rest.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from db.connect import connect
from graph.state import LifeVaultState

#: Decisions accepted from a human. "edit" carries replacement parameters.
APPROVE = "approve"
EDIT = "edit"
REJECT = "reject"
DECISIONS = (APPROVE, EDIT, REJECT)


class ApprovalError(Exception):
    """Raised when a decision cannot be applied to a proposal."""


class ProposalNotFound(ApprovalError):
    pass


class ProposalAlreadyDecided(ApprovalError):
    pass


# ---------------------------------------------------------------------
# Proposal storage
# ---------------------------------------------------------------------


def load_proposal(proposal_id: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Load one proposal row as a plain dict, with JSON fields decoded."""
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM proposals WHERE id=?", (proposal_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ProposalNotFound(f"no proposal with id {proposal_id!r}")
    return _decode(row)


def list_proposals(
    status: Optional[str] = None, limit: int = 50, db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    conn = connect(db_path)
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM proposals WHERE status=? ORDER BY created_at DESC "
                "LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM proposals ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    finally:
        conn.close()
    return [_decode(row) for row in rows]


def _decode(row) -> Dict[str, Any]:
    record = dict(row)
    for field, default in (("parameters", {}), ("evidence_document_hashes", [])):
        try:
            record[field] = json.loads(record.get(field) or json.dumps(default))
        except (TypeError, ValueError):
            record[field] = default
    if record.get("edit_diff"):
        try:
            record["edit_diff"] = json.loads(record["edit_diff"])
        except (TypeError, ValueError):
            pass
    return record


def record_decision(
    proposal_id: str,
    status: str,
    note: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    edit_diff: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the human's decision onto the proposal row."""
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status FROM proposals WHERE id=?", (proposal_id,)
        ).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            raise ProposalNotFound(f"no proposal with id {proposal_id!r}")
        if row["status"] != "pending":
            conn.execute("ROLLBACK")
            raise ProposalAlreadyDecided(
                f"proposal {proposal_id} is already {row['status']!r}"
            )
        fields = ["status=?", "decision=?", "decided_at=?"]
        values: List[Any] = [status, note, datetime.now(timezone.utc).isoformat()]
        if parameters is not None:
            fields.append("parameters=?")
            values.append(json.dumps(parameters, sort_keys=True))
        if edit_diff is not None:
            fields.append("edit_diff=?")
            values.append(json.dumps(edit_diff, sort_keys=True))
        values.append(proposal_id)
        conn.execute(
            f"UPDATE proposals SET {', '.join(fields)} WHERE id=?", tuple(values)
        )
        conn.execute("COMMIT")
    except ApprovalError:
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return load_proposal(proposal_id, db_path)


def mark_status(
    proposal_id: str,
    status: str,
    db_path: Optional[str] = None,
) -> None:
    """Move a decided proposal to a terminal status (executed / error)."""
    conn = connect(db_path)
    try:
        conn.execute(
            "UPDATE proposals SET status=? WHERE id=?", (status, proposal_id)
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Edits
# ---------------------------------------------------------------------


def compute_edit_diff(
    original: Dict[str, Any], edited: Dict[str, Any]
) -> Dict[str, Any]:
    """A field-by-field record of what the human changed.

    Stored in the audit row, because "approved after changing the date" and
    "approved as proposed" are materially different events and the chain has
    to be able to tell them apart.
    """
    diff: Dict[str, Any] = {}
    for key in sorted(set(original) | set(edited)):
        before = original.get(key)
        after = edited.get(key)
        if before != after:
            diff[key] = {"from": before, "to": after}
    return diff


def apply_edit(
    proposal: Dict[str, Any], edited_parameters: Optional[Dict[str, Any]]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Merge a human's parameter edits and re-run the policy gate.

    Edited values are re-validated from scratch. A human editing a field is
    not a reason to trust it: the same allow-list, Pydantic validation, vault
    containment and citation checks apply, so an edit cannot be used to slip
    a bad value past policy.
    """
    from policy.policy import check_proposal

    original = dict(proposal.get("parameters") or {})
    merged = {**original, **(edited_parameters or {})}

    verdict = check_proposal(
        tool=proposal["tool"],
        parameters=merged,
        evidence_document_hashes=proposal.get("evidence_document_hashes"),
    )
    if not verdict.allowed:
        raise ApprovalError(
            "edited parameters were rejected by policy: "
            + "; ".join(verdict.reasons)
        )
    final = verdict.validated_parameters or merged
    return final, compute_edit_diff(original, final)


# ---------------------------------------------------------------------
# Graph node
# ---------------------------------------------------------------------


def human_approval(state: LifeVaultState) -> dict:
    """The `human_approval` node.

    The graph is compiled with `interrupt_before=["human_approval"]`, so on
    the first pass execution stops *before* this function runs. It only ever
    executes on resume, by which point the decision is already in state --
    so all it does is normalize the value the routing function reads.
    """
    proposal = state.get("proposal")
    if proposal is None:
        return {"approval_status": None}

    status = state.get("approval_status")
    if status in ("approved", "denied"):
        return {"approval_status": status}
    # Resumed with a raw decision word rather than a status.
    if status == APPROVE or status == EDIT:
        return {"approval_status": "approved"}
    if status == REJECT:
        return {"approval_status": "denied"}
    return {"approval_status": "pending"}
