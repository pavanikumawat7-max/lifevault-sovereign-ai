"""Persisted indexing status, pause/resume, and start-indexing controls."""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from api.schemas import (
    GetIndexStatusResponse,
    IndexStatus,
    PauseIndexResponse,
    ResumeIndexResponse,
    StartIndexRequest,
    StartIndexResponse,
)
from fastapi import APIRouter, HTTPException
from db.connect import connect

router = APIRouter(prefix="/api/index", tags=["index"])

# Guards against overlapping background ingest runs triggered from the UI.
# A local single-user tool needs no more than a simple in-process lock.
_ingest_lock = threading.Lock()
_ingest_running = False


@router.post("/start", response_model=StartIndexResponse)
def start_index(req: StartIndexRequest | None = None) -> StartIndexResponse:
    """Kick off indexing for one or all approved, enabled, unpaused roots.

    Runs the real ingestion pipeline (worker.index.ingest_root) in a
    background thread so the request returns immediately and the UI can
    poll GET /api/index/status for live progress -- no manual
    scripts/index_folder.py needed.
    """
    global _ingest_running
    req = req or StartIndexRequest()

    conn = connect()
    try:
        if req.root_id is not None:
            row = conn.execute(
                "SELECT id, enabled, paused FROM index_roots WHERE id=?",
                (req.root_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="root not found")
            if not row["enabled"]:
                raise HTTPException(status_code=400, detail="root is not enabled")
            if row["paused"]:
                raise HTTPException(status_code=400, detail="root is paused")
            root_ids = [row["id"]]
        else:
            rows = conn.execute(
                "SELECT id FROM index_roots WHERE enabled=1 AND paused=0"
            ).fetchall()
            root_ids = [row["id"] for row in rows]
    finally:
        conn.close()

    if not root_ids:
        conn = connect()
        try:
            return StartIndexResponse(
                started=False,
                roots_queued=[],
                status=_status(conn),
                message="No enabled, unpaused roots to index. Grant a folder first.",
            )
        finally:
            conn.close()

    with _ingest_lock:
        if _ingest_running:
            conn = connect()
            try:
                return StartIndexResponse(
                    started=False,
                    roots_queued=[],
                    status=_status(conn),
                    message="Indexing is already running.",
                )
            finally:
                conn.close()
        _ingest_running = True

    def _run() -> None:
        global _ingest_running
        try:
            from worker.index import ingest_root

            for root_id in root_ids:
                ingest_root(root_id)
        finally:
            with _ingest_lock:
                _ingest_running = False

    threading.Thread(target=_run, name="lifevault-ingest", daemon=True).start()

    conn = connect()
    try:
        conn.execute(
            "UPDATE index_state SET state='scanning', message=? WHERE id=1",
            (f"Indexing started for {len(root_ids)} root(s)",),
        )
        status = _status(conn)
        return StartIndexResponse(
            started=True,
            roots_queued=root_ids,
            status=status,
            message=f"Indexing started for {len(root_ids)} root(s).",
        )
    finally:
        conn.close()

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
