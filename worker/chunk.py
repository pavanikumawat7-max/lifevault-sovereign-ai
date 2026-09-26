"""Token-approximate, overlapping, page-preserving text chunking."""
from __future__ import annotations

import re
from dataclasses import dataclass

from worker.parse import ParsedPage

TOKEN_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    text: str
    page: int
    position: int


def chunk_pages(
    pages: list[ParsedPage], target_tokens: int = 500, overlap_tokens: int = 60
) -> list[TextChunk]:
    if target_tokens <= 0 or overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("Chunk sizes must satisfy 0 <= overlap < target")
    chunks: list[TextChunk] = []
    step = target_tokens - overlap_tokens
    for page in pages:
        matches = list(TOKEN_RE.finditer(page.text))
        for start in range(0, len(matches), step):
            window = matches[start : start + target_tokens]
            if not window:
                break
            char_start = window[0].start()
            char_end = window[-1].end()
            text = page.text[char_start:char_end].strip()
            if text:
                chunks.append(
                    TextChunk(
                        chunk_index=len(chunks),
                        text=text,
                        page=page.page,
                        position=char_start,
                    )
                )
            if start + target_tokens >= len(matches):
                break
    return chunks