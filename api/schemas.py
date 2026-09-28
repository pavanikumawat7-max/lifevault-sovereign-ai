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


class StartIndexRequest(BaseModel):
    root_id: Optional[int] = None


class StartIndexResponse(BaseModel):
    started: bool
    roots_queued: List[int] = Field(default_factory=list)
    status: IndexStatus
    message: Optional[str] = None


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
    # --- S3 additions (additive: new optional fields with defaults) ------
    # The S3 acceptance gate requires every citation to name a path and a
    # page; the S1 shape had neither. Existing clients that ignore these
    # keep working unchanged.
    #: Absolute path of the file this citation came from.
    path: Optional[str] = None
    #: 1-based page number within that file, when known.
    page: Optional[int] = None
    #: Other paths holding byte-identical content ("also found at").
    also_found_at: List[str] = Field(default_factory=list)
    #: The chunk label the model used in its answer ("C1", "C2", ...).
    label: Optional[str] = None


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    citations: List[Citation] = Field(default_factory=list)
    proposal_id: Optional[str] = None
    grounded: bool = False
    # --- S3 additions (additive: new optional fields with defaults) ------
    #: The model's own 0.0-1.0 estimate that the answer is fully supported.
    confidence: float = 0.0
    #: Why grounding passed or failed. Set when `grounded` is False so the
    #: UI can explain a "could not verify" instead of showing a bare string.
    verification_reason: Optional[str] = None
    #: Which local model answered ("fixture" in fixture mode).
    model: Optional[str] = None
    #: Wall-clock milliseconds for retrieve + answer + verify.
    latency_ms: Optional[int] = None


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
    # --- S6 additions (additive: new optional fields with defaults) ------
    #: The chunk the value was read out of, for citation back to a page.
    source_chunk_id: Optional[int] = None
    #: Title of the source document, so the UI need not fetch it separately.
    document_title: Optional[str] = None
    #: Human-readable field name ("Expiry Date") for display.
    label: Optional[str] = None


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
    # --- S7 additions (additive: new optional fields with defaults) ------
    #: Sensitivity label from the policy rule, shown as a badge.
    tier: Optional[str] = None
    #: Parameter names whose values came from document text and look like
    #: injected instructions. The approval card highlights these.
    untrusted_fields: List[str] = Field(default_factory=list)
    #: LangGraph thread to resume; how approval survives an API restart.
    thread_id: Optional[str] = None
    created_at: Optional[str] = None
    decided_at: Optional[str] = None


class ApprovalDecisionRequest(BaseModel):
    # --- S7 additive change ---------------------------------------------
    # S1 froze this as Literal["approve", "deny"]. S7 needs "edit" and the
    # plan's own wording is approve / edit / reject, so the literal is
    # WIDENED (never narrowed) and the two original values keep working
    # unchanged. "deny" and "reject" are accepted as synonyms.
    decision: Literal["approve", "deny", "edit", "reject"]
    note: Optional[str] = None
    #: Replacement parameters for decision="edit". Merged over the proposal's
    #: parameters and re-validated by policy before anything executes.
    parameters: Optional[Dict[str, Any]] = None


class ListProposalsResponse(BaseModel):
    """S7 additive response: the approval queue."""

    proposals: List[Proposal] = Field(default_factory=list)


class ApprovalDecisionResponse(BaseModel):
    proposal: Proposal
    # --- S7 additions (additive: new optional fields with defaults) ------
    #: True when the approved action actually ran.
    executed: bool = False
    #: The tool's own result (paths written, ids created).
    result: Optional[Dict[str, Any]] = None
    #: What the human changed, field by field: {"due_date": {"from":..,"to":..}}.
    edit_diff: Optional[Dict[str, Any]] = None
    #: Audit rows appended while handling this decision.
    audit_events: List[Dict[str, Any]] = Field(default_factory=list)
    #: Set when the decision could not be applied.
    message: Optional[str] = None


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
