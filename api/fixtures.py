"""Canned fixture data for S1 stub routes.

Centralized here so every route module (and the smoke test) sees the same
shapes. None of this is persisted -- it's process-local, in-memory data
good enough to prove routing/serialization/UI wiring end-to-end without
real documents, a real model, or real worker output.
"""
from __future__ import annotations

from api.schemas import (
    DocumentDetailResponse,
    DocumentSummary,
    Fact,
    FileLocation,
    IndexRoot,
    MemoryEntry,
    Proposal,
)

FIXTURE_ROOT = IndexRoot(
    id=1,
    path="/home/user/Documents",
    enabled=True,
    exclude_patterns=["*.tmp", "~$*"],
    granted_at="2026-01-01T00:00:00+00:00",
    paused=False,
)

FIXTURE_DOCUMENT_HASH = "deadbeefcafebabe0000000000000000000000000000000000000000000000"

FIXTURE_DOCUMENT = DocumentSummary(
    content_hash=FIXTURE_DOCUMENT_HASH,
    title="Sample Insurance Policy.pdf",
    doc_type="pdf",
    size_bytes=245_112,
    page_count=6,
    mime_type="application/pdf",
    status="active",
    first_seen_at="2026-01-02T09:15:00+00:00",
    last_seen_at="2026-01-02T09:15:00+00:00",
)

FIXTURE_DOCUMENT_DETAIL = DocumentDetailResponse(
    document=FIXTURE_DOCUMENT,
    locations=[
        FileLocation(
            path="/home/user/Documents/Insurance/Sample Insurance Policy.pdf",
            missing=False,
            last_verified_at="2026-01-02T09:15:00+00:00",
        )
    ],
    fact_count=1,
    chunk_count=0,
)

FIXTURE_FACT = Fact(
    id=1,
    type="policy_number",
    field="Policy Number",
    value="POL-000000",
    norm_value="POL-000000",
    source_document_hash=FIXTURE_DOCUMENT_HASH,
    source_quote="Policy Number: POL-000000",
    user_corrected=False,
)

FIXTURE_PROPOSAL = Proposal(
    id="stub-proposal-1",
    tool="noop",
    parameters={},
    rationale="S1 stub proposal -- no real proposals are generated yet.",
    evidence_document_hashes=[FIXTURE_DOCUMENT_HASH],
    status="pending",
    decision=None,
)

FIXTURE_MEMORY_ENTRIES: list[MemoryEntry] = []
