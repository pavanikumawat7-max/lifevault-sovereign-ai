"""OCR for images and scanned PDF pages (S5).

Uses RapidOCR (ONNX runtime, fully local -- no cloud, no API key). The
models download once on first use and are then cached under the user's home
directory by RapidOCR itself.

Two policies worth knowing:

  * **OCR is a fallback, never the default.** A PDF page that already has an
    embedded text layer is used as-is; OCR only runs on pages with almost no
    text (`MIN_PAGE_CHARS`). Extracted text is always better than rasterizing
    and guessing at it, and OCR on 100 pages that did not need it would make
    indexing unusable on a laptop.
  * **A near-empty result is recorded as empty.** An image that yields two
    characters of noise is worse than no text: it pollutes the index and
    produces citations that make no sense. Those are stored as metadata only,
    which is what the handover plan asks for.

The engine is loaded lazily and only once. Importing this module must stay
cheap, because `worker/parse.py` imports it on every ingest whether OCR ends
up being needed or not.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: A PDF page with fewer than this many characters of embedded text is
#: treated as a scan and sent to OCR. The handover plan says "about 50".
MIN_PAGE_CHARS = 50

#: Below this, an OCR result is treated as no text at all.
MIN_OCR_CHARS = 8

#: Rasterize scanned pages at this scale. 2.0 (~144 dpi) is the point where
#: accuracy stops improving much and memory use starts to hurt on 8 GB.
RENDER_SCALE = 2.0

#: Only these are OCR'd as whole images.
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"})

_engine: Optional[Any] = None
_engine_lock = threading.Lock()
_engine_failed = False


class OCRUnavailable(RuntimeError):
    """Raised when RapidOCR cannot be loaded at all."""


def is_available() -> bool:
    """Can OCR run? Never raises, so callers can branch cheaply."""
    try:
        return _get_engine() is not None
    except OCRUnavailable:
        return False


def _get_engine() -> Any:
    """Load RapidOCR once, lazily, and remember a failure so we stop retrying."""
    global _engine, _engine_failed
    if _engine is not None:
        return _engine
    if _engine_failed:
        raise OCRUnavailable("RapidOCR previously failed to load")

    with _engine_lock:
        if _engine is not None:
            return _engine
        try:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
            return _engine
        except Exception as exc:  # noqa: BLE001 - optional dependency
            _engine_failed = True
            raise OCRUnavailable(
                f"RapidOCR is not usable ({exc}). Install it with "
                "`pip install rapidocr-onnxruntime` to index screenshots and "
                "scanned PDFs; everything else still works without it."
            ) from exc


def _preprocess(image: Any) -> Any:
    """Grayscale + autocontrast, as the handover plan specifies.

    Both genuinely help on screenshots and phone photos of documents: the
    detector cares about edge contrast, not colour.
    """
    try:
        from PIL import ImageOps

        return ImageOps.autocontrast(image.convert("L"))
    except Exception:  # noqa: BLE001 - preprocessing is an optimization
        return image


def _run(image_or_path: Any) -> str:
    """Run OCR and join the recognized lines in reading order."""
    engine = _get_engine()
    try:
        import numpy as np
        from PIL import Image

        if isinstance(image_or_path, (str, Path)):
            image = Image.open(image_or_path)
        else:
            image = image_or_path
        prepared = _preprocess(image)
        # RapidOCR wants a 3-channel array.
        array = np.array(prepared.convert("RGB"))
        result, _elapsed = engine(array)
    except OCRUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - a bad image is not fatal
        logger.warning("OCR failed on %s: %s", image_or_path, exc)
        return ""

    if not result:
        return ""
    lines: List[str] = []
    for entry in result:
        # RapidOCR returns [box, text, confidence] per detected line.
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            text = str(entry[1]).strip()
            if text:
                lines.append(text)
    return "\n".join(lines)


def ocr_image(path: str | Path) -> str:
    """OCR a whole image file. Returns "" when there is no usable text."""
    text = _run(Path(path))
    return text if len(text.strip()) >= MIN_OCR_CHARS else ""


def ocr_pdf_page(page: Any) -> str:
    """OCR one PyMuPDF page by rendering it to a bitmap first."""
    try:
        import io

        from PIL import Image

        try:
            import pymupdf
        except ImportError:  # pragma: no cover
            import fitz as pymupdf

        matrix = pymupdf.Matrix(RENDER_SCALE, RENDER_SCALE)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    except OCRUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not rasterize page for OCR: %s", exc)
        return ""

    text = _run(image)
    return text if len(text.strip()) >= MIN_OCR_CHARS else ""


def needs_ocr(text: str) -> bool:
    """Is this page's embedded text thin enough to be worth OCR'ing?"""
    return len((text or "").strip()) < MIN_PAGE_CHARS


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def ocr_file(path: str | Path) -> Tuple[str, bool]:
    """OCR any supported file. Returns (text, ocr_was_used).

    `ocr_was_used=True` with empty text means "we tried and found nothing" --
    an image with no readable text, stored as metadata only.
    """
    path = Path(path)
    if not is_image(path):
        return "", False
    try:
        return ocr_image(path), True
    except OCRUnavailable as exc:
        logger.info("skipping OCR for %s: %s", path.name, exc)
        return "", False
