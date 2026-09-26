"""Stable Worker contract backed by the S2 ingestion implementation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class ScanResult:
    """Result of scanning one index root for new/changed/missing files."""

    root_id: int
    files_found: int = 0
    files_new: int = 0
    files_changed: int = 0
    files_missing: int = 0


@dataclass
class ParseResult:
    """Result of parsing one document (by content hash) into chunks."""

    content_hash: str
    chunks_created: int = 0


@dataclass
class IndexResult:
    """Result of indexing one document's chunks (FTS5 + vectors)."""

    content_hash: str
    chunks_indexed: int = 0
    fts_indexed: bool = False
    vector_indexed: bool = False


class Worker:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path

    def scan(self, root_path: str) -> ScanResult:
        from worker.index import approve_root
        from worker.scanner import scan_root

        root_id = approve_root(root_path, db_path=self.db_path)
        return scan_root(root_id, self.db_path).result

    def parse(self, content_hash: str) -> ParseResult:
        from worker.index import parse_document

        return parse_document(content_hash, self.db_path)

    def index(self, content_hash: str) -> IndexResult:
        from worker.index import index_document

        return index_document(content_hash, self.db_path)
