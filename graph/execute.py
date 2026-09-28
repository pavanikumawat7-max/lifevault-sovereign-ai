"""Tool execution (S7).

One rule, and the whole session's safety rests on it: **a tool runs only
after a human approved this specific proposal.** `execute` re-reads the
proposal row from the database and refuses unless its status is
`approved` -- it does not trust the graph state it was handed, because
state can be edited by a resume call while the row is the durable record of
what the human actually decided.

Policy is re-checked here too, immediately before the handler runs. That is
deliberate belt-and-braces: the parameters passed the gate at proposal time
and again at edit time, and checking once more means no path exists where a
handler receives parameters no policy pass has seen.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from graph.state import LifeVaultState


def execute_proposal(
    proposal_id: str,
    db_path: Optional[str] = None,
    registry: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run the approved tool for `proposal_id`. Returns a result dict.

    Never raises on a tool failure: a crash inside a handler becomes an
    `ok: False` result so `audit_and_memory` can still record what happened.
    An unapproved proposal is a refusal, not an error.
    """
    from graph import approval as approval_module
    from policy.policy import check_proposal

    proposal = approval_module.load_proposal(proposal_id, db_path)

    if proposal.get("status") != "approved":
        return {
            "ok": False,
            "executed": False,
            "proposal_id": proposal_id,
            "tool": proposal.get("tool"),
            "reason": (
                f"refusing to execute: proposal status is "
                f"{proposal.get('status')!r}, not 'approved'"
            ),
        }

    verdict = check_proposal(
        tool=proposal["tool"],
        parameters=proposal.get("parameters"),
        evidence_document_hashes=proposal.get("evidence_document_hashes"),
    )
    if not verdict.allowed:
        return {
            "ok": False,
            "executed": False,
            "proposal_id": proposal_id,
            "tool": proposal.get("tool"),
            "reason": "policy denied at execution time: " + "; ".join(verdict.reasons),
            "policy": verdict.to_dict(),
        }

    if registry is None:
        from api.tools import default_registry as registry

    spec = registry.get(proposal["tool"])
    if spec is None or spec.handler is None:
        return {
            "ok": False,
            "executed": False,
            "proposal_id": proposal_id,
            "tool": proposal.get("tool"),
            "reason": f"no handler registered for tool {proposal['tool']!r}",
        }

    parameters = verdict.validated_parameters or proposal.get("parameters") or {}
    try:
        output = spec.handler(parameters, proposal_id=proposal_id, db_path=db_path)
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        approval_module.mark_status(proposal_id, "error", db_path)
        return {
            "ok": False,
            "executed": False,
            "proposal_id": proposal_id,
            "tool": proposal["tool"],
            "reason": f"{type(exc).__name__}: {exc}",
        }

    approval_module.mark_status(proposal_id, "executed", db_path)
    return {
        "ok": True,
        "executed": True,
        "proposal_id": proposal_id,
        "tool": proposal["tool"],
        "output": output,
    }


def execute(state: LifeVaultState) -> dict:
    """The `execute` node. Only reached when routing saw an approval."""
    proposal = state.get("proposal")
    if not isinstance(proposal, dict) or not proposal.get("id"):
        return {"execution_result": None}
    return {"execution_result": execute_proposal(str(proposal["id"]))}
