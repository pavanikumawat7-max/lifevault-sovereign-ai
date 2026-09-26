"""Persisted indexing status and pause/resume controls."""
from __future__ import annotations

from datetime import datetime, timezone

from api.schemas import (
    GetIndexStatusResponse,
    IndexStatus,
    PauseIndexResponse,
    ResumeIndexResponse,
)
from fastapi import APIRouter
from db.connect import connect

router = APIRouter(prefix="/api/index", tags=["index"])

@router.post("/pause", response_model=PauseIndexResponse)
def pause_index() -> PauseIndexResponse:
    now = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE index_roots SET paused=1, paused_at=?, updated_at=?", (now, now)
        )
        conn.execute(
            "UPDATE index_state SET state='paused', message='Indexing paused' WHERE id=1"
        )
        conn.execute("COMMIT")
        return PauseIndexResponse(status=_status(conn))
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@router.post("/resume", response_model=ResumeIndexResponse)
def resume_index() -> ResumeIndexResponse:
    now = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE index_roots SET paused=0, paused_at=NULL, updated_at=?", (now,)
        )
        conn.execute(
            "UPDATE index_state SET state='idle', message='Indexing ready' WHERE id=1"
        )
        conn.execute("COMMIT")
        return ResumeIndexResponse(status=_status(conn))
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@router.get("/status", response_model=GetIndexStatusResponse)
def get_index_status() -> GetIndexStatusResponse:
    conn = connect()
    try:
        return GetIndexStatusResponse(status=_status(conn))
    finally:
        conn.close()


def _status(conn) -> IndexStatus:
    row = conn.execute(
        "SELECT state, last_run_at, message FROM index_state WHERE id=1"
    ).fetchone()
    counts = conn.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM index_roots WHERE enabled=1) roots_total,
          (SELECT COUNT(*) FROM index_roots WHERE enabled=1 AND paused=1) roots_paused,
          (SELECT COUNT(*) FROM documents WHERE status='active') documents_indexed,
          (SELECT COUNT(*) FROM chunks WHERE superseded=0) chunks_indexed
        """
    ).fetchone()
    return IndexStatus(
        state=row["state"] if row else "idle",
        roots_total=counts["roots_total"],
        roots_paused=counts["roots_paused"],
        documents_indexed=counts["documents_indexed"],
        chunks_indexed=counts["chunks_indexed"],
        last_run_at=row["last_run_at"] if row else None,
        message=row["message"] if row else None,
    )
