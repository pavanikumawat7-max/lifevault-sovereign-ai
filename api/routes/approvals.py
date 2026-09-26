"""POST /api/approvals/{proposal_id}.

S1 stub: records the decision onto an in-memory fixture Proposal only.
Real approval behavior -- resuming the LangGraph `human_approval`
interrupt, writing to the `proposals` table, executing the tool -- lands
in a later session (see graph/nodes.py:human_approval).
"""
from __future__ import annotations

from fastapi import APIRouter

from api.fixtures import FIXTURE_PROPOSAL
from api.schemas import ApprovalDecisionRequest, ApprovalDecisionResponse, Proposal

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

_PROPOSAL_STATE: Proposal = FIXTURE_PROPOSAL.model_copy()


@router.post("/{proposal_id}", response_model=ApprovalDecisionResponse)
def decide_approval(proposal_id: str, req: ApprovalDecisionRequest) -> ApprovalDecisionResponse:
    global _PROPOSAL_STATE
    new_status = "approved" if req.decision == "approve" else "denied"
    _PROPOSAL_STATE = _PROPOSAL_STATE.model_copy(
        update={"id": proposal_id, "status": new_status, "decision": req.note}
    )
    return ApprovalDecisionResponse(proposal=_PROPOSAL_STATE)
