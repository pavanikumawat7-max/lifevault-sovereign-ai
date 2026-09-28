"""GET /api/memory -- real last-decision memory (S7).

Backed by the `memory` table, which `graph/audit_memory.py` upserts after
every approved or rejected action. Scope is deliberately "last decision per
tool", not a full history: it is what supplies defaults for the next
proposal and answers "what did I do about my Dell?", without turning into an
unbounded log of everything the user has ever done.
"""
from __future__ import annotations

from fastapi import APIRouter

from api.schemas import MemoryEntry, MemoryResponse
from graph.audit_memory import list_memory

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("", response_model=MemoryResponse)
def get_memory() -> MemoryResponse:
    return MemoryResponse(
        entries=[
            MemoryEntry(
                key=entry["key"],
                last_decision=entry.get("last_decision"),
                context=entry.get("context") or {},
                updated_at=entry.get("updated_at"),
            )
            for entry in list_memory()
        ]
    )
