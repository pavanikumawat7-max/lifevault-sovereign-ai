"""S2 ingestion orchestration and transactional chunk/vector writes."""
from __future__ import annotations

import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import llm
from config import get_config
from db.connect import connect
from db.init_db import init_db
from worker.chunk import TextChunk, chunk_pages
from worker.parse import parse_pdf
from worker.scanner import ScanBatch, scan_root
from worker.worker import IndexResult, ParseResult, ScanResult

BATCH_SIZE = 32


def approve_root(
    path: str | Path,
    exclude_patterns: list[str] | None = None,
    db_path: str | None = None,
) -> int:
    """Persist consent and return the root id."""
    init_db(db_path)
    normalized = str(Path(path).expanduser().absolute())
    now = _utcnow()
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO index_roots
                (path, enabled, exclude_patterns, granted_at, paused, updated_at)
            VALUES (?, 1, ?, ?, 0, ?)
            ON CONFLICT(path) DO UPDATE SET
                enabled=1, exclude_patterns=excluded.exclude_patterns,
                granted_at=excluded.granted_at, paused=0, paused_at=NULL,
                updated_at=excluded.updated_at
            """,
            (normalized, json.dumps(exclude_patterns or []), now, now),
        )
        root_id = conn.execute(
            "SELECT id FROM index_roots WHERE path=?", (normalized,)
        ).fetchone()["id"]
        conn.execute("COMMIT")
        return root_id
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def ingest_root(root_id: int, db_path: str | None = None) -> dict:
    """Scan and index all new/changed PDFs under one approved root."""
    init_db(db_path)
    _set_state(db_path, "scanning", "Scanning approved root")
    try:
        batch = scan_root(root_id, db_path)
        _set_state(db_path, "indexing", "Parsing and indexing documents")
        processed = 0
        chunks_indexed = 0
        vectors_available = vector_table_available(db_path)
        seen_hashes: set[str] = set()
        for document in batch.documents:
            if document.content_hash in seen_hashes or not document.needs_processing:
                continue
            seen_hashes.add(document.content_hash)
            parsed = parse_pdf(document.path, document.content_hash)
            chunks = chunk_pages(parsed.pages)
            embeddings = embed_chunks(chunks)
            write_index(
                document.content_hash,
                len(parsed.pages),
                chunks,
                embeddings,
                db_path,
            )
            processed += 1
            chunks_indexed += len(chunks)

        message = (
            f"Found {batch.result.files_found}; unique {batch.result.files_new}; "
            f"duplicates {batch.duplicates}; skipped {batch.skipped}; "
            f"processed {processed}"
        )
        _finish_state(db_path, batch, processed, message)
        return {
            "root_id": root_id,
            "found": batch.result.files_found,
            "unique": batch.result.files_new,
            "duplicates": batch.duplicates,
            "skipped": batch.skipped,
            "processed": processed,
            "chunks": chunks_indexed,
            "vectors": vectors_available,
        }
    except Exception as exc:
        _set_state(db_path, "error", str(exc))
        raise


def parse_document(content_hash: str, db_path: str | None = None) -> ParseResult:
    """Parse and persist page-aware chunks for an existing document."""
    path = _document_path(content_hash, db_path)
    parsed = parse_pdf(path, content_hash)
    chunks = chunk_pages(parsed.pages)
    _replace_chunks(content_hash, len(parsed.pages), chunks, db_path)
    return ParseResult(content_hash=content_hash, chunks_created=len(chunks))


def index_document(content_hash: str, db_path: str | None = None) -> IndexResult:
    """Embed existing chunks and populate the configured vector table."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, chunk_index, text, page, position FROM chunks "
            "WHERE content_hash=? AND superseded=0 ORDER BY chunk_index",
            (content_hash,),
        ).fetchall()
    finally:
        conn.close()
    chunks = [
        TextChunk(
            chunk_index=row["chunk_index"],
            text=row["text"],
            page=row["page"],
            position=row["position"] or 0,
        )
        for row in rows
    ]
    embeddings = embed_chunks(chunks)
    vector_indexed = _write_vectors(
        [(row["id"], vector) for row, vector in zip(rows, embeddings)],
        db_path,
    )
    return IndexResult(
        content_hash=content_hash,
        chunks_indexed=len(chunks),
        fts_indexed=True,
        vector_indexed=vector_indexed,
    )


def embed_chunks(chunks: list[TextChunk]) -> list[list[float]]:
    """Embed in explicit batches while reusing the frozen single-text wrapper."""
    vectors: list[list[float]] = []
    dimension = get_config().embedding_dimension
    for offset in range(0, len(chunks), BATCH_SIZE):
        for chunk in chunks[offset : offset + BATCH_SIZE]:
            vector = llm.embed(chunk.text)
            if len(vector) != dimension:
                raise ValueError(
                    f"Embedding dimension {len(vector)} does not match {dimension}"
                )
            vectors.append(vector)
    return vectors


def write_index(
    content_hash: str,
    page_count: int,
    chunks: list[TextChunk],
    embeddings: list[list[float]],
    db_path: str | None = None,
) -> bool:
    """Replace chunks and vectors for a document in one short transaction."""
    conn = connect(db_path)
    try:
        has_vectors = _has_vector_table(conn)
        conn.execute("BEGIN IMMEDIATE")
        if has_vectors:
            old_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM chunks WHERE content_hash=?", (content_hash,)
                )
            ]
            conn.executemany(
                "DELETE FROM chunks_vec WHERE chunk_id=?", [(value,) for value in old_ids]
            )
        conn.execute("DELETE FROM chunks WHERE content_hash=?", (content_hash,))
        pairs: list[tuple[int, list[float]]] = []
        for chunk, vector in zip(chunks, embeddings):
            cursor = conn.execute(
                """
                INSERT INTO chunks
                    (content_hash, chunk_index, text, page, position)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    content_hash,
                    chunk.chunk_index,
                    chunk.text,
                    chunk.page,
                    chunk.position,
                ),
            )
            pairs.append((cursor.lastrowid, vector))
        conn.execute(
            "UPDATE documents SET page_count=?, last_seen_at=? WHERE content_hash=?",
            (page_count, _utcnow(), content_hash),
        )
        if has_vectors:
            conn.executemany(
                "INSERT INTO chunks_vec (chunk_id, embedding) VALUES (?, ?)",
                [(chunk_id, _serialize(vector)) for chunk_id, vector in pairs],
            )
        conn.execute("COMMIT")
        return has_vectors
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def vector_table_available(db_path: str | None = None) -> bool:
    conn = connect(db_path)
    try:
        return _has_vector_table(conn)
    finally:
        conn.close()


def _replace_chunks(
    content_hash: str,
    page_count: int,
    chunks: list[TextChunk],
    db_path: str | None,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM chunks WHERE content_hash=?", (content_hash,))
        conn.executemany(
            "INSERT INTO chunks (content_hash, chunk_index, text, page, position) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (content_hash, c.chunk_index, c.text, c.page, c.position)
                for c in chunks
            ],
        )
        conn.execute(
            "UPDATE documents SET page_count=? WHERE content_hash=?",
            (page_count, content_hash),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _write_vectors(
    pairs: list[tuple[int, list[float]]], db_path: str | None
) -> bool:
    conn = connect(db_path)
    try:
        if not _has_vector_table(conn):
            return False
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            "DELETE FROM chunks_vec WHERE chunk_id=?", [(row_id,) for row_id, _ in pairs]
        )
        conn.executemany(
            "INSERT INTO chunks_vec (chunk_id, embedding) VALUES (?, ?)",
            [(row_id, _serialize(vector)) for row_id, vector in pairs],
        )
        conn.execute("COMMIT")
        return True
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _document_path(content_hash: str, db_path: str | None) -> str:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT path FROM file_locations "
            "WHERE content_hash=? AND missing=0 ORDER BY id LIMIT 1",
            (content_hash,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise FileNotFoundError(f"No available location for {content_hash}")
    return row["path"]


def _has_vector_table(conn) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='chunks_vec'"
        ).fetchone()
        is not None
    )


def _serialize(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _set_state(db_path: str | None, state: str, message: str) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            "UPDATE index_state SET state=?, message=? WHERE id=1", (state, message)
        )
    finally:
        conn.close()


def _finish_state(
    db_path: str | None,
    batch: ScanBatch,
    processed: int,
    message: str,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            """
            UPDATE index_state SET
                state='idle', files_found=?, files_unique=?,
                files_duplicates=?, files_skipped=?, files_processed=?,
                last_run_at=?, message=?
            WHERE id=1
            """,
            (
                batch.result.files_found,
                batch.result.files_new,
                batch.duplicates,
                batch.skipped,
                processed,
                _utcnow(),
                message,
            ),
        )
    finally:
        conn.close()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()