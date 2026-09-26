"""Persisted folder-consent endpoints."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from db.connect import connect
from api.schemas import (
    CreateRootRequest,
    CreateRootResponse,
    DeleteRootResponse,
    IndexRoot,
    ListRootsResponse,
)

router = APIRouter(prefix="/api/roots", tags=["roots"])


@router.get("", response_model=ListRootsResponse)
def list_roots() -> ListRootsResponse:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, path, enabled, exclude_patterns, granted_at, paused "
            "FROM index_roots ORDER BY id"
        ).fetchall()
        return ListRootsResponse(roots=[_to_model(row) for row in rows])
    finally:
        conn.close()


@router.post("", response_model=CreateRootResponse, status_code=201)
def create_root(req: CreateRootRequest) -> CreateRootResponse:
    path = str(Path(req.path).expanduser().absolute())
    now = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO index_roots
                (path, enabled, exclude_patterns, granted_at, paused, updated_at)
            VALUES (?, 1, ?, ?, 0, ?)
            ON CONFLICT(path) DO UPDATE SET
                enabled=1,
                exclude_patterns=excluded.exclude_patterns,
                granted_at=excluded.granted_at,
                paused=0,
                paused_at=NULL,
                updated_at=excluded.updated_at
            """,
            (path, json.dumps(req.exclude_patterns), now, now),
        )
        row = conn.execute(
            "SELECT id, path, enabled, exclude_patterns, granted_at, paused "
            "FROM index_roots WHERE path = ?",
            (path,),
        ).fetchone()
        conn.execute("COMMIT")
        return CreateRootResponse(root=_to_model(row))
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@router.delete("/{root_id}", response_model=DeleteRootResponse)
def delete_root(root_id: int) -> DeleteRootResponse:
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        exists = conn.execute(
            "SELECT 1 FROM index_roots WHERE id = ?", (root_id,)
        ).fetchone()
        if exists is None:
            # DELETE is idempotent; this also preserves the S1 response shape.
            conn.execute("COMMIT")
            return DeleteRootResponse(id=root_id, deleted=True)

        hashes = [
            row["content_hash"]
            for row in conn.execute(
                "SELECT DISTINCT content_hash FROM file_locations WHERE root_id = ?",
                (root_id,),
            )
        ]
        conn.execute("DELETE FROM file_locations WHERE root_id = ?", (root_id,))
        conn.execute("DELETE FROM index_roots WHERE id = ?", (root_id,))
        for content_hash in hashes:
            remaining = conn.execute(
                "SELECT 1 FROM file_locations WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
            if remaining is None:
                if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='chunks_vec'"
                ).fetchone():
                    chunk_ids = [
                        row["id"]
                        for row in conn.execute(
                            "SELECT id FROM chunks WHERE content_hash=?",
                            (content_hash,),
                        )
                    ]
                    conn.executemany(
                        "DELETE FROM chunks_vec WHERE chunk_id=?",
                        [(chunk_id,) for chunk_id in chunk_ids],
                    )
                conn.execute(
                    "DELETE FROM documents WHERE content_hash = ?", (content_hash,)
                )
        conn.execute("COMMIT")
        return DeleteRootResponse(id=root_id, deleted=True)
    except HTTPException:
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _to_model(row) -> IndexRoot:
    try:
        patterns = json.loads(row["exclude_patterns"] or "[]")
    except json.JSONDecodeError:
        patterns = []
    return IndexRoot(
        id=row["id"],
        path=row["path"],
        enabled=bool(row["enabled"]),
        exclude_patterns=patterns,
        granted_at=row["granted_at"],
        paused=bool(row["paused"]),
    )
