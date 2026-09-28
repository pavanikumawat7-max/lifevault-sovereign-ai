"""Audit and memory writes (S7).

The last node in the graph, and the one that makes every run accountable.
It appends one hash-chained `audit_log` row per turn and upserts a `memory`
row recording what the user decided about this kind of action.

The audit row carries everything the handover plan asks for -- proposal,
evidence, model, policy verdict, decision, edit diff, result, hashes -- so
the chain is a complete account of the turn and not just a timestamp.

Two things it deliberately does not do:

  * **It never stores document text.** Only content hashes, paths and the
    short quote that was already surfaced as a citation. The audit log is
    the one table most likely to be exported or screenshotted, so it does
    not become a second copy of the user's documents.
  * **It never fails the turn.** An audit write that throws would lose the
    answer the user already has. Failures are reported on the state's
    `error` channel instead, and `api.audit.AuditLog.verify()` will show the
    gap because the chain simply has no row for that turn.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from db.connect import connect
from graph.state import LifeVaultState

#: Audit event names. Stable strings -- the audit viewer filters on them.
EVENT_TURN = "chat_turn"
EVENT_PROPOSAL = "action_proposed"
EVENT_DECISION = "action_decided"
EVENT_EXECUTION = "action_executed"
EVENT_POLICY_DENIED = "action_policy_denied"


def _citation_digest(citations: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Citations reduced to what an audit reader needs, no document text."""
    digest: List[Dict[str, Any]] = []
    for citation in citations or []:
        digest.append(
            {
                "label": citation.get("label"),
                "document_hash": citation.get("document_hash"),
                "chunk_id": citation.get("chunk_id"),
                "path": citation.get("path"),
                "page": citation.get("page"),
            }
        )
    return digest


def write_audit(
    event: str, payload: Dict[str, Any], db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Append one audit row. Returns the row, or None if the write failed."""
    from api.audit import AuditLog

    conn = connect(db_path)
    try:
        return AuditLog(conn).log(event, payload)
    except Exception as exc:  # noqa: BLE001 - never break the turn over audit
        print(f"[graph.audit_memory] audit write failed for {event}: {exc}")
        return None
    finally:
        conn.close()


def upsert_memory(
    key: str,
    last_decision: Optional[str],
    context: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> None:
    """Record the latest decision for `key`.

    "Last decision" memory only, as scoped: this overwrites rather than
    appends, so it can answer "what did I do about my Dell?" and supply
    defaults for the next proposal without becoming an unbounded history.
    """
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO memory (key, last_decision, context, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET last_decision=excluded.last_decision, "
            "context=excluded.context, updated_at=excluded.updated_at",
            (
                key,
                last_decision,
                json.dumps(context or {}, sort_keys=True),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[graph.audit_memory] memory write failed for {key}: {exc}")
    finally:
        conn.close()


def list_memory(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT key, last_decision, context, updated_at FROM memory "
            "ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()
    entries: List[Dict[str, Any]] = []
    for row in rows:
        try:
            context = json.loads(row["context"] or "{}")
        except (TypeError, ValueError):
            context = {}
        entries.append(
            {
                "key": row["key"],
                "last_decision": row["last_decision"],
                "context": context if isinstance(context, dict) else {},
                "updated_at": row["updated_at"],
            }
        )
    return entries


def _memory_context_from_execution(
    proposal: Dict[str, Any], result: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """What the next proposal should learn from this one.

    `lead_days` is the interesting field: if the user edited a reminder to
    fire 45 days before expiry instead of 30, the next reminder proposal
    should default to 45. That is the "because you did this before" chip in
    the S8 approval card.
    """
    context: Dict[str, Any] = {
        "tool": proposal.get("tool"),
        "proposal_id": proposal.get("id"),
        "parameters": proposal.get("parameters") or proposal.get("params") or {},
        "evidence_document_hashes": list(
            proposal.get("evidence_document_hashes") or []
        ),
    }
    if result and result.get("output"):
        output = result["output"]
        context["result"] = {
            key: output.get(key)
            for key in ("tool", "vault_relative_path", "due_date", "subject", "sent")
            if key in output
        }

    edit_diff = proposal.get("edit_diff") or {}
    if isinstance(edit_diff, dict) and "due_date" in edit_diff:
        lead = _lead_days_from_edit(proposal, edit_diff)
        if lead is not None:
            context["lead_days"] = lead
    return context


def _lead_days_from_edit(
    proposal: Dict[str, Any], edit_diff: Dict[str, Any]
) -> Optional[int]:
    """Infer the lead time a human chose, from an edited due date."""
    from datetime import date

    change = edit_diff.get("due_date") or {}
    new_due = change.get("to")
    if not isinstance(new_due, str):
        return None

    title = str((proposal.get("parameters") or {}).get("title") or "")
    import re

    match = re.search(r"(\d{4}-\d{2}-\d{2})", title)
    expiry_text: Optional[str] = match.group(1) if match else None
    if expiry_text is None:
        from worker.facts import normalize_date

        found = re.search(r"expires?\s+(.+)$", title, re.IGNORECASE)
        if found:
            expiry_text = normalize_date(found.group(1).strip())
    if not expiry_text:
        return None
    try:
        return (date.fromisoformat(expiry_text) - date.fromisoformat(new_due)).days
    except ValueError:
        return None


# ---------------------------------------------------------------------
# Graph node
# ---------------------------------------------------------------------


def audit_and_memory(state: LifeVaultState) -> dict:
    """The `audit_and_memory` node: append audit rows, upsert memory.

    Every path through the graph reaches here -- answered-and-done, policy
    denied, rejected by the human, or executed -- so every turn leaves a
    trace. Which rows get written depends on how far the turn got.
    """
    events: List[Dict[str, Any]] = list(state.get("audit_events") or [])

    def record(event: str, payload: Dict[str, Any]) -> None:
        row = write_audit(event, payload)
        if row is not None:
            events.append(
                {"id": row["id"], "event": row["event"], "ts": row["ts"],
                 "row_hash": row["row_hash"]}
            )

    proposal = state.get("proposal")
    citations = _citation_digest(state.get("citations") or [])
    verification = state.get("verification") or {}

    # 1. The turn itself: question, grounding outcome, evidence, model.
    record(
        EVENT_TURN,
        {
            "conversation_id": state.get("conversation_id"),
            "question": state.get("user_message"),
            "grounded": bool(state.get("grounded")),
            "verification_reason": verification.get("reason"),
            "confidence": state.get("confidence"),
            "model": state.get("answer_model"),
            "citations": citations,
            "fact_count": len(state.get("retrieved_facts") or []),
        },
    )

    # 2. Candidates policy refused, so a denial is never invisible.
    for candidate in state.get("proposal_candidates") or []:
        if isinstance(candidate, dict) and candidate.get("policy_rejected"):
            record(
                EVENT_POLICY_DENIED,
                {
                    "tool": candidate.get("tool"),
                    "policy": candidate.get("policy_rejected"),
                    "evidence_document_hashes": list(
                        candidate.get("evidence_document_hashes") or []
                    ),
                },
            )

    if isinstance(proposal, dict) and proposal.get("id"):
        proposal_id = str(proposal["id"])
        # Re-read the row: it is the durable record of what the human did.
        try:
            from graph import approval as approval_module

            stored = approval_module.load_proposal(proposal_id)
        except Exception:  # noqa: BLE001
            stored = dict(proposal)

        base = {
            "proposal_id": proposal_id,
            "tool": stored.get("tool"),
            "parameters": stored.get("parameters"),
            "rationale": stored.get("rationale"),
            "evidence_document_hashes": list(
                stored.get("evidence_document_hashes") or []
            ),
            "tier": stored.get("tier"),
            "model": state.get("answer_model"),
            "policy_verdict": state.get("policy_decision"),
            "untrusted_fields": list(proposal.get("untrusted_fields") or []),
            "citations": citations,
        }

        # 3. The proposal as put to the human.
        record(EVENT_PROPOSAL, base)

        approval_status = state.get("approval_status")
        if approval_status in ("approved", "denied"):
            record(
                EVENT_DECISION,
                {
                    **base,
                    "decision": approval_status,
                    "note": stored.get("decision"),
                    "edit_diff": stored.get("edit_diff") or {},
                    "decided_at": stored.get("decided_at"),
                },
            )

        # 4. The outcome, and what to remember for next time.
        result = state.get("execution_result")
        if isinstance(result, dict):
            record(
                EVENT_EXECUTION,
                {
                    **base,
                    "ok": bool(result.get("ok")),
                    "executed": bool(result.get("executed")),
                    "reason": result.get("reason"),
                    "output": result.get("output"),
                },
            )

        if approval_status in ("approved", "denied"):
            from graph.propose import memory_key

            upsert_memory(
                key=memory_key(str(stored.get("tool"))),
                last_decision=approval_status,
                context=_memory_context_from_execution(
                    stored, result if isinstance(result, dict) else None
                ),
            )

    return {"audit_events": events}
