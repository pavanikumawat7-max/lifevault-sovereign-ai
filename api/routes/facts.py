"""GET /api/facts, PATCH /api/facts/{id}.

S1 stub: reads/mutates a single in-memory fixture Fact. Real fact storage
lives in the `facts` table (see db/schema.sql) once extraction exists.
"""
from __future__ import annotations

from fastapi import APIRouter

from api.fixtures import FIXTURE_FACT
from api.schemas import Fact, ListFactsResponse, UpdateFactRequest, UpdateFactResponse

router = APIRouter(prefix="/api/facts", tags=["facts"])

_FACT_STATE: Fact = FIXTURE_FACT.model_copy()


@router.get("", response_model=ListFactsResponse)
def list_facts() -> ListFactsResponse:
    return ListFactsResponse(facts=[_FACT_STATE])


@router.patch("/{fact_id}", response_model=UpdateFactResponse)
def update_fact(fact_id: int, req: UpdateFactRequest) -> UpdateFactResponse:
    global _FACT_STATE
    updates = req.model_dump(exclude_unset=True)
    _FACT_STATE = _FACT_STATE.model_copy(update=updates)
    return UpdateFactResponse(fact=_FACT_STATE)
