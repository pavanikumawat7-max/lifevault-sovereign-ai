"""POST /api/index/pause, POST /api/index/resume, GET /api/index/status.

S1 stub: mutates an in-memory status dict only. Real indexing state lands
with worker/worker.py's real implementation in a later session.
"""
from __future__ import annotations

from api.schemas import (
    GetIndexStatusResponse,
    IndexStatus,
    PauseIndexResponse,
    ResumeIndexResponse,
)
from fastapi import APIRouter

router = APIRouter(prefix="/api/index", tags=["index"])

_STATE: dict = {
    "state": "idle",
    "roots_total": 1,
    "roots_paused": 0,
    "documents_indexed": 0,
    "chunks_indexed": 0,
    "last_run_at": None,
    "message": "S1 stub: no real indexing has run yet.",
}


@router.post("/pause", response_model=PauseIndexResponse)
def pause_index() -> PauseIndexResponse:
    _STATE["state"] = "paused"
    _STATE["roots_paused"] = _STATE["roots_total"]
    return PauseIndexResponse(status=IndexStatus(**_STATE))


@router.post("/resume", response_model=ResumeIndexResponse)
def resume_index() -> ResumeIndexResponse:
    _STATE["state"] = "idle"
    _STATE["roots_paused"] = 0
    return ResumeIndexResponse(status=IndexStatus(**_STATE))


@router.get("/status", response_model=GetIndexStatusResponse)
def get_index_status() -> GetIndexStatusResponse:
    return GetIndexStatusResponse(status=IndexStatus(**_STATE))
