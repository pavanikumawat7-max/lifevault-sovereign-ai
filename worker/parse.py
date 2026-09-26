"""Page-aware PDF text extraction. OCR is deliberately out of scope."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import pymupdf
except ImportError:  # pragma: no cover - compatibility with older PyMuPDF
    import fitz as pymupdf


@dataclass(frozen=True)
class ParsedPage:
    page: int
    text: str


@dataclass(frozen=True)
class ParsedDocument:
    content_hash: str
    path: str
    pages: list[ParsedPage]


def parse_pdf(path: str | Path, content_hash: str) -> ParsedDocument:
    source = Path(path)
    pages: list[ParsedPage] = []
    with pymupdf.open(source) as document:
        for index, page in enumerate(document):
            pages.append(ParsedPage(page=index + 1, text=page.get_text("text")))
    return ParsedDocument(content_hash=content_hash, path=str(source), pages=pages)