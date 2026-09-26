"""Worker interface: scan / parse / index.

S1 defines the CONTRACT only -- method names, signatures, and result
shapes -- so later sessions can implement real filesystem scanning, PDF
parsing/chunking, and FTS5/vector indexing without changing how the rest
of the system (the graph, the API, run.py) calls into the worker.

Every method deliberately raises NotImplementedError in S1. Do not add
real scanning/parsing/indexing logic here yet -- that's explicitly out of
scope for S1 (see the project brief's scope rule).
"""
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
    """S1 interface only. Real behavior lands in a later session.

    Intended lifecycle (for later sessions to implement):
        scan(root_path)   -> discover files under an index_root, dedupe
                              by content hash, record file_locations
        parse(content_hash) -> extract text and split it into `chunks` rows
        index(content_hash) -> populate chunks_fts and chunks_vec for the
                                document's chunks
    """

    def scan(self, root_path: str) -> ScanResult:
        raise NotImplementedError("Worker.scan is a S1 interface stub")

    def parse(self, content_hash: str) -> ParseResult:
        raise NotImplementedError("Worker.parse is a S1 interface stub")

    def index(self, content_hash: str) -> IndexResult:
        raise NotImplementedError("Worker.index is a S1 interface stub")
