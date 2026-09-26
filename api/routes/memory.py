"""GET /api/memory.

S1 stub: returns an empty fixture list. Real last-decision memory is
populated by the LangGraph `audit_and_memory` node in a later session.
"""
from __future__ import annotations

from fastapi import APIRouter

from api.fixtures import FIXTURE_MEMORY_ENTRIES
from api.schemas import MemoryResponse

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("", response_model=MemoryResponse)
def get_memory() -> MemoryResponse:
    return MemoryResponse(entries=list(FIXTURE_MEMORY_ENTRIES))
