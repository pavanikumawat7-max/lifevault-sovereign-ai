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
    #: S5 addition: True when this page's text came from OCR, not a text layer.
    ocr: bool = False


@dataclass(frozen=True)
class ParsedDocument:
    content_hash: str
    path: str
    pages: list[ParsedPage]


def parse_pdf(
    path: str | Path, content_hash: str, use_ocr: bool = True
) -> ParsedDocument:
    """Extract text per page, falling back to OCR on pages that have none.

    S5 addition: a page whose embedded text layer is nearly empty is a scan,
    so it is rendered and OCR'd. Pages that already carry text are never
    OCR'd -- the embedded layer is more accurate and vastly faster.
    """
    source = Path(path)
    pages: list[ParsedPage] = []
    with pymupdf.open(source) as document:
        for index, page in enumerate(document):
            text = page.get_text("text")
            ocr_used = False
            if use_ocr:
                from worker import ocr as ocr_module

                if ocr_module.needs_ocr(text):
                    try:
                        recognized = ocr_module.ocr_pdf_page(page)
                    except ocr_module.OCRUnavailable:
                        recognized = ""
                    if recognized:
                        text = recognized
                        ocr_used = True
            pages.append(ParsedPage(page=index + 1, text=text, ocr=ocr_used))
    return ParsedDocument(content_hash=content_hash, path=str(source), pages=pages)


def parse_image(path: str | Path, content_hash: str) -> ParsedDocument:
    """OCR a whole image (a screenshot, a photo of a document) as one page.

    An image that yields no usable text still returns one empty page, so the
    document is recorded and deduplicated -- metadata only, which is what the
    handover plan asks for. It simply will not match any search.
    """
    from worker import ocr as ocr_module

    source = Path(path)
    text, ocr_used = ocr_module.ocr_file(source)
    return ParsedDocument(
        content_hash=content_hash,
        path=str(source),
        pages=[ParsedPage(page=1, text=text, ocr=ocr_used)],
    )


def parse_document(path: str | Path, content_hash: str) -> ParsedDocument:
    """Parse any supported file, dispatching on its extension."""
    from worker import ocr as ocr_module

    source = Path(path)
    if ocr_module.is_image(source):
        return parse_image(source, content_hash)
    return parse_pdf(source, content_hash)