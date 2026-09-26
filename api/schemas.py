"""Frozen S1 API contracts.

Every request/response model used by api/routes/*. These are FROZEN as of
S1: later sessions may add new OPTIONAL fields (with defaults) but must
NOT rename or remove any field defined here, and must not change a
field's type in a way that breaks existing clients (the React UI shell in
particular). If a later session genuinely needs a breaking change, that's
a new, explicitly-versioned model -- not an edit to one of these.

Pydantic v2 models throughout.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------


class ErrorResponse(BaseModel):
    detail: str


# ---------------------------------------------------------------------
# Roots: GET/POST /api/roots, DELETE /api/roots/{id}
# ---------------------------------------------------------------------


class IndexRoot(BaseModel):
    id: int
    path: str
    enabled: bool = True
    exclude_patterns: List[str] = Field(default_factory=list)
    granted_at: Optional[str] = None
    paused: bool = False


class ListRootsResponse(BaseModel):
    roots: List[IndexRoot]


class CreateRootRequest(BaseModel):
    path: str
    exclude_patterns: List[str] = Field(default_factory=list)


class CreateRootResponse(BaseModel):
    root: IndexRoot


class DeleteRootResponse(BaseModel):
    id: int
    deleted: bool


# ---------------------------------------------------------------------
# Index: POST /api/index/pause, POST /api/index/resume, GET /api/index/status
# ---------------------------------------------------------------------

IndexState = Literal["idle", "scanning", "indexing", "paused", "error"]


class IndexStatus(BaseModel):
    state: IndexState = "idle"
    roots_total: int = 0
    roots_paused: int = 0
    documents_indexed: int = 0
    chunks_indexed: int = 0
    last_run_at: Optional[str] = None
    message: Optional[str] = None


class PauseIndexResponse(BaseModel):
    status: IndexStatus


class ResumeIndexResponse(BaseModel):
    status: IndexStatus


class GetIndexStatusResponse(BaseModel):
    status: IndexStatus


# ---------------------------------------------------------------------
# Chat: POST /api/chat
# ---------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    history: List[ChatMessage] = Field(default_factory=list)


class Citation(BaseModel):
    document_hash: str
    chunk_id: Optional[int] = None
    quote: str


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    citations: List[Citation] = Field(default_factory=list)
    proposal_id: Optional[str] = None
    grounded: bool = False


# ---------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------


class DocumentSummary(BaseModel):
    content_hash: str
    title: Optional[str] = None
    doc_type: Optional[str] = None
    size_bytes: Optional[int] = None
    page_count: Optional[int] = None
    mime_type: Optional[str] = None
    status: str = "active"
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None


class FileLocation(BaseModel):
    path: str
    missing: bool = False
    last_verified_at: Optional[str] = None


class DocumentDetailResponse(BaseModel):
    document: DocumentSummary
    locations: List[FileLocation] = Field(default_factory=list)
    fact_count: int = 0
    chunk_count: int = 0


class DocumentPreviewResponse(BaseModel):
    content_hash: str
    preview_text: str
    page_count: Optional[int] = None


class OpenDocumentRequest(BaseModel):
    path: Optional[str] = None


class OpenDocumentResponse(BaseModel):
    opened: bool
    path: Optional[str] = None
    message: Optional[str] = None


class RevealDocumentResponse(BaseModel):
    revealed: bool
    path: Optional[str] = None
    message: Optional[str] = None


# ---------------------------------------------------------------------
# Facts: GET /api/facts, PATCH /api/facts/{id}
# ---------------------------------------------------------------------


class Fact(BaseModel):
    id: int
    type: str
    field: str
    value: Optional[str] = None
    norm_value: Optional[str] = None
    source_document_hash: Optional[str] = None
    source_quote: Optional[str] = None
    user_corrected: bool = False


class ListFactsResponse(BaseModel):
    facts: List[Fact]


class UpdateFactRequest(BaseModel):
    value: Optional[str] = None
    norm_value: Optional[str] = None
    user_corrected: Optional[bool] = None


class UpdateFactResponse(BaseModel):
    fact: Fact


# ---------------------------------------------------------------------
# Approvals: POST /api/approvals/{proposal_id}
# ---------------------------------------------------------------------


class Proposal(BaseModel):
    id: str
    tool: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    rationale: Optional[str] = None
    evidence_document_hashes: List[str] = Field(default_factory=list)
    status: str = "pending"
    decision: Optional[str] = None


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "deny"]
    note: Optional[str] = None


class ApprovalDecisionResponse(BaseModel):
    proposal: Proposal


# ---------------------------------------------------------------------
# Memory: GET /api/memory
# ---------------------------------------------------------------------


class MemoryEntry(BaseModel):
    key: str
    last_decision: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    updated_at: Optional[str] = None


class MemoryResponse(BaseModel):
    entries: List[MemoryEntry]


# ---------------------------------------------------------------------
# Audit: GET /api/audit, GET /api/audit/verify
# ---------------------------------------------------------------------


class AuditEntry(BaseModel):
    id: int
    event: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    ts: str
    prev_hash: str
    row_hash: str


class AuditListResponse(BaseModel):
    entries: List[AuditEntry]


class AuditVerifyResponse(BaseModel):
    valid: bool
    reason: Optional[str] = None
    row_id: Optional[int] = None
    rows_checked: Optional[int] = None
