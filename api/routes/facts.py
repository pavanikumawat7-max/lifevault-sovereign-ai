"""GET /api/facts, PATCH /api/facts/{id} -- real, backed by the facts table (S6).

Query parameters (both optional, both additive to the frozen contract):

  * `type=warranty|invoice|other` -- filter by document type
  * `expiring_within=<days>`      -- expiry facts due within N days, oldest
                                     first. Already-expired items are
                                     included on purpose: "this lapsed two
                                     months ago" is the answer a user needs.

A PATCH records a human correction. It sets `user_corrected=1`, which makes
the row immune to being overwritten the next time extraction runs -- see
worker/facts.py:store_facts. That is the whole point of the flag: a person
fixing a misread date must not have to fix it again after every re-index.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_db
from api.schemas import Fact, ListFactsResponse, UpdateFactRequest, UpdateFactResponse
from worker import facts as facts_module

router = APIRouter(prefix="/api/facts", tags=["facts"])


def _to_model(row: dict) -> Fact:
    return Fact(
        id=row["id"],
        type=row["type"],
        field=row["field"],
        value=row.get("value"),
        norm_value=row.get("norm_value"),
        source_document_hash=row.get("source_document_hash"),
        source_quote=row.get("source_quote"),
        user_corrected=bool(row.get("user_corrected")),
        # --- S6 additive optional fields ---
        source_chunk_id=row.get("source_chunk_id"),
        document_title=row.get("document_title"),
        label=facts_module._LABELS.get(row["field"]),
    )


@router.get("", response_model=ListFactsResponse)
def list_facts(
    type: Optional[str] = Query(None, description="warranty | invoice | other"),
    expiring_within: Optional[int] = Query(
        None, ge=0, le=36500, description="Expiry facts due within N days"
    ),
    conn=Depends(get_db),
) -> ListFactsResponse:
    rows = facts_module.list_facts(
        fact_type=type, expiring_within=expiring_within, conn=conn
    )
    return ListFactsResponse(facts=[_to_model(row) for row in rows])


@router.patch("/{fact_id}", response_model=UpdateFactResponse)
def update_fact(
    fact_id: int, req: UpdateFactRequest, conn=Depends(get_db)
) -> UpdateFactResponse:
    row = conn.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No fact with id {fact_id}")

    updates = req.model_dump(exclude_unset=True)
    value = updates.get("value", row["value"])
    # Re-normalize a corrected date so expiring_within keeps working on it.
    if "norm_value" in updates:
        norm_value = updates["norm_value"]
    elif "value" in updates and row["field"] in ("expiry_date", "start_date", "date"):
        norm_value = facts_module.normalize_date(value) or row["norm_value"]
    elif "value" in updates and row["field"] == "total":
        norm_value = facts_module.normalize_amount(value) or row["norm_value"]
    else:
        norm_value = row["norm_value"]

    # Any PATCH is a human touching this row, so it is corrected from now on
    # unless the caller explicitly says otherwise.
    user_corrected = updates.get("user_corrected", True)

    conn.execute(
        "UPDATE facts SET value=?, norm_value=?, user_corrected=?, updated_at=? "
        "WHERE id=?",
        (value, norm_value, int(bool(user_corrected)),
         datetime.now(timezone.utc).isoformat(), fact_id),
    )
    updated = conn.execute(
        "SELECT f.*, d.title AS document_title FROM facts f "
        "LEFT JOIN documents d ON d.content_hash = f.source_document_hash "
        "WHERE f.id=?",
        (fact_id,),
    ).fetchone()
    return UpdateFactResponse(fact=_to_model(dict(updated)))
