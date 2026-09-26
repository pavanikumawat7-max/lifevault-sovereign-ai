"""GET /api/documents/{hash}, GET /api/documents/{hash}/preview,
POST /api/documents/{hash}/open, POST /api/documents/{hash}/reveal.

S1 stub: every hash returns the same fixture document/detail so the UI's
document views have something real to render against. Real lookup by
content_hash (and 404 handling for unknown hashes) lands once the worker
actually populates `documents`.
"""
from __future__ import annotations

from fastapi import APIRouter

from api.fixtures import FIXTURE_DOCUMENT_DETAIL
from api.schemas import (
    DocumentDetailResponse,
    DocumentPreviewResponse,
    OpenDocumentRequest,
    OpenDocumentResponse,
    RevealDocumentResponse,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("/{content_hash}", response_model=DocumentDetailResponse)
def get_document(content_hash: str) -> DocumentDetailResponse:
    return FIXTURE_DOCUMENT_DETAIL


@router.get("/{content_hash}/preview", response_model=DocumentPreviewResponse)
def preview_document(content_hash: str) -> DocumentPreviewResponse:
    return DocumentPreviewResponse(
        content_hash=content_hash,
        preview_text="[S1 stub] No real document preview yet.",
        page_count=FIXTURE_DOCUMENT_DETAIL.document.page_count,
    )


@router.post("/{content_hash}/open", response_model=OpenDocumentResponse)
def open_document(content_hash: str, req: OpenDocumentRequest) -> OpenDocumentResponse:
    return OpenDocumentResponse(
        opened=False,
        path=req.path,
        message="S1 stub: opening documents is not implemented yet.",
    )


@router.post("/{content_hash}/reveal", response_model=RevealDocumentResponse)
def reveal_document(content_hash: str) -> RevealDocumentResponse:
    return RevealDocumentResponse(
        revealed=False,
        path=None,
        message="S1 stub: revealing documents in a file browser is not implemented yet.",
    )
