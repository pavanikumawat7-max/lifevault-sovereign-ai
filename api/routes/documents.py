"""GET /api/documents/{hash}, GET /api/documents/{hash}/preview,
POST /api/documents/{hash}/open, POST /api/documents/{hash}/reveal.

S4: real lookup by content_hash against the database the worker (S2) and
retrieval (S3) already populate. A document that isn't indexed 404s rather
than returning stub data -- the citation viewer needs to be able to tell
"not found" apart from "found, but empty".

`open`/`reveal` are best-effort local OS actions (this is a local-first
desktop tool, not a hosted service): they shell out to the platform's
default file-open / reveal-in-file-manager command. Any failure (headless
environment, missing binary, path no longer on disk) is reported back in
the response body rather than raised as a 500 -- the citation viewer should
be able to show "couldn't open that automatically, here's the path" and
keep working.
"""
from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from db.connect import connect
from api.schemas import (
    DocumentDetailResponse,
    DocumentPreviewResponse,
    DocumentSummary,
    FileLocation,
    OpenDocumentRequest,
    OpenDocumentResponse,
    RevealDocumentResponse,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])

PREVIEW_CHUNK_LIMIT = 6  # enough chunks to give a meaningful preview
PREVIEW_CHAR_LIMIT = 4000


def _get_document_row(conn, content_hash: str):
    row = conn.execute(
        """
        SELECT content_hash, title, doc_type, size_bytes, page_count,
               mime_type, status, first_seen_at, last_seen_at
        FROM documents WHERE content_hash = ?
        """,
        (content_hash,),
    ).fetchone()
    return row


def _locations(conn, content_hash: str) -> list[FileLocation]:
    rows = conn.execute(
        "SELECT path, missing, last_verified_at FROM file_locations "
        "WHERE content_hash = ? ORDER BY id",
        (content_hash,),
    ).fetchall()
    return [
        FileLocation(
            path=row["path"],
            missing=bool(row["missing"]),
            last_verified_at=row["last_verified_at"],
        )
        for row in rows
    ]


def _primary_path(locations: list[FileLocation]) -> Optional[str]:
    """The best path to act on: first non-missing location, else the first."""
    for loc in locations:
        if not loc.missing:
            return loc.path
    return locations[0].path if locations else None


@router.get("/{content_hash}", response_model=DocumentDetailResponse)
def get_document(content_hash: str) -> DocumentDetailResponse:
    conn = connect()
    try:
        row = _get_document_row(conn, content_hash)
        if row is None:
            raise HTTPException(status_code=404, detail="document not found")

        locations = _locations(conn, content_hash)
        fact_count = conn.execute(
            "SELECT COUNT(*) AS n FROM facts WHERE source_document_hash = ?",
            (content_hash,),
        ).fetchone()["n"]
        chunk_count = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE content_hash = ? AND superseded = 0",
            (content_hash,),
        ).fetchone()["n"]

        return DocumentDetailResponse(
            document=DocumentSummary(
                content_hash=row["content_hash"],
                title=row["title"],
                doc_type=row["doc_type"],
                size_bytes=row["size_bytes"],
                page_count=row["page_count"],
                mime_type=row["mime_type"],
                status=row["status"],
                first_seen_at=row["first_seen_at"],
                last_seen_at=row["last_seen_at"],
            ),
            locations=locations,
            fact_count=fact_count,
            chunk_count=chunk_count,
        )
    finally:
        conn.close()


@router.get("/{content_hash}/preview", response_model=DocumentPreviewResponse)
def preview_document(content_hash: str) -> DocumentPreviewResponse:
    conn = connect()
    try:
        row = _get_document_row(conn, content_hash)
        if row is None:
            raise HTTPException(status_code=404, detail="document not found")

        chunk_rows = conn.execute(
            "SELECT text FROM chunks WHERE content_hash = ? AND superseded = 0 "
            "ORDER BY chunk_index LIMIT ?",
            (content_hash, PREVIEW_CHUNK_LIMIT),
        ).fetchall()

        if chunk_rows:
            preview_text = "\n\n".join(r["text"] for r in chunk_rows)[:PREVIEW_CHAR_LIMIT]
        else:
            preview_text = "No extracted text is indexed for this document yet."

        return DocumentPreviewResponse(
            content_hash=content_hash,
            preview_text=preview_text,
            page_count=row["page_count"],
        )
    finally:
        conn.close()


def _resolve_target_path(conn, content_hash: str, requested_path: Optional[str]) -> Optional[str]:
    locations = _locations(conn, content_hash)
    if requested_path:
        for loc in locations:
            if loc.path == requested_path:
                return requested_path
        # An explicit but unrecognized path is still honored if it exists
        # on disk -- the UI may pass an "also_found_at" path we know about
        # from a citation but haven't stored a location row for yet.
        return requested_path
    return _primary_path(locations)


def _shell_open(path: str, reveal: bool) -> tuple[bool, str]:
    system = platform.system()
    try:
        if system == "Darwin":
            cmd = ["open", "-R", path] if reveal else ["open", path]
        elif system == "Windows":
            cmd = (
                ["explorer", "/select,", path]
                if reveal
                else ["cmd", "/c", "start", "", path]
            )
        else:  # Linux and friends: no reliable "reveal", open the folder instead
            target = str(Path(path).parent) if reveal else path
            cmd = ["xdg-open", target]
        subprocess.run(cmd, check=False, timeout=5)
        return True, f"Handed off to the OS ({system})."
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not launch a file handler on this machine: {exc}"


@router.post("/{content_hash}/open", response_model=OpenDocumentResponse)
def open_document(content_hash: str, req: OpenDocumentRequest) -> OpenDocumentResponse:
    conn = connect()
    try:
        row = _get_document_row(conn, content_hash)
        if row is None:
            raise HTTPException(status_code=404, detail="document not found")

        target = _resolve_target_path(conn, content_hash, req.path)
        if not target:
            return OpenDocumentResponse(
                opened=False, path=None, message="No known file location for this document."
            )
        if not Path(target).exists():
            return OpenDocumentResponse(
                opened=False,
                path=target,
                message="File no longer exists at that path.",
            )

        ok, message = _shell_open(target, reveal=False)
        return OpenDocumentResponse(opened=ok, path=target, message=message)
    finally:
        conn.close()


@router.post("/{content_hash}/reveal", response_model=RevealDocumentResponse)
def reveal_document(content_hash: str) -> RevealDocumentResponse:
    conn = connect()
    try:
        row = _get_document_row(conn, content_hash)
        if row is None:
            raise HTTPException(status_code=404, detail="document not found")

        target = _primary_path(_locations(conn, content_hash))
        if not target:
            return RevealDocumentResponse(
                revealed=False, path=None, message="No known file location for this document."
            )
        if not Path(target).exists():
            return RevealDocumentResponse(
                revealed=False,
                path=target,
                message="File no longer exists at that path.",
            )

        ok, message = _shell_open(target, reveal=True)
        return RevealDocumentResponse(revealed=ok, path=target, message=message)
    finally:
        conn.close()
