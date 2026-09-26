"""GET /api/audit, GET /api/audit/verify.

Unlike every other route module, this one is backed by REAL logic:
api/audit.py's hash-chained append-only log. These two endpoints simply
read from it and wrap the result in the frozen response models.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.audit import AuditLog
from api.deps import get_db
from api.schemas import AuditEntry, AuditListResponse, AuditVerifyResponse

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=AuditListResponse)
def list_audit(limit: int = 100, conn: sqlite3.Connection = Depends(get_db)) -> AuditListResponse:
    audit = AuditLog(conn)
    entries = [AuditEntry(**row) for row in audit.list_recent(limit=limit)]
    return AuditListResponse(entries=entries)


@router.get("/verify", response_model=AuditVerifyResponse)
def verify_audit(conn: sqlite3.Connection = Depends(get_db)) -> AuditVerifyResponse:
    audit = AuditLog(conn)
    result = audit.verify()
    return AuditVerifyResponse(**result)
