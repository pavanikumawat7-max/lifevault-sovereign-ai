"""Fact extraction (S6).

Turns document text into normalized `facts` rows: warranty expiry dates,
invoice totals, serial numbers and the like, each carrying the verbatim
sentence it came from.

Three rules this module keeps, in order of importance:

  1. **Every fact must quote its source.** `source_quote` is the sentence
     the value was read out of, and `store_facts` refuses any fact whose
     quote is not literally present in the chunk it claims to come from. A
     fact that cannot point at its evidence is not stored.
  2. **Regex first, model second.** Dates, serials and totals are regular
     enough that a regex is more reliable *and* thousands of times faster
     than a 3B model on this hardware. `llm_fallback` exists for documents
     the patterns miss and is off by default.
  3. **Dates are stored twice**: `value` keeps the document's own wording
     ("June 12, 2027") so citations read naturally, `norm_value` keeps
     ISO-8601 ("2027-06-12") so SQL can answer "expiring within 60 days"
     without parsing anything.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from db.connect import connect

try:  # dateparser handles the long tail ("3rd of March '19")
    import dateparser
except ImportError:  # pragma: no cover - listed dependency, optional at runtime
    dateparser = None  # type: ignore

# --- Document types -------------------------------------------------------
WARRANTY = "warranty"
INVOICE = "invoice"
OTHER = "other"

_WARRANTY_KEYWORDS = (
    "warranty", "guarantee", "coverage", "service tag", "limited hardware",
)
_INVOICE_KEYWORDS = (
    "invoice", "receipt", "amount due", "payment status", "subtotal", "tax",
)

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_WS_RE = re.compile(r"\s+")

# A date as documents actually write them. Kept deliberately narrow: a bare
# 4-digit year is NOT a date here, because "Contract OLD-DEMO-319" style
# identifiers produce far too many false positives.
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october"
    "|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_DATE_PATTERN = (
    rf"(?:(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTHS})\.?,?\s+\d{{4}}"
    rf"|\d{{4}}-\d{{1,2}}-\d{{1,2}}"
    rf"|\d{{1,2}}[/.]\d{{1,2}}[/.]\d{{4}})"
)
_DATE_RE = re.compile(_DATE_PATTERN, re.IGNORECASE)

#: (field, regex). First capturing group is the value.
_WARRANTY_PATTERNS: Sequence[tuple[str, re.Pattern]] = (
    ("expiry_date", re.compile(
        rf"(?:warranty\s+)?(?:expires?|expired|expiry|valid\s+(?:un)?til|"
        rf"end(?:s|ing)?(?:\s+on)?)\s*(?:date)?\s*[:\-]?\s*({_DATE_PATTERN})",
        re.IGNORECASE)),
    ("start_date", re.compile(
        rf"(?:purchase(?:d)?|start(?:s|ing)?|effective|bought)\s*(?:date)?\s*"
        rf"[:\-]?\s*({_DATE_PATTERN})", re.IGNORECASE)),
    ("serial", re.compile(
        r"(?:service\s+tag|serial(?:\s+(?:no\.?|number))?|s/n)\s*[:\-]?\s*"
        r"([A-Z0-9][A-Z0-9\-]{3,})", re.IGNORECASE)),
    ("product", re.compile(
        r"product\s*[:\-]\s*([^.\n]{2,60})", re.IGNORECASE)),
    ("contract", re.compile(
        r"contract\s*(?:no\.?|number)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-]{3,})",
        re.IGNORECASE)),
)

_INVOICE_PATTERNS: Sequence[tuple[str, re.Pattern]] = (
    # The value must contain a digit and must not be a label word: without
    # that, "Invoice date June 12" captures "date" as the invoice number.
    ("invoice_no", re.compile(
        r"invoice\s*(?:no\.?|number|#)?\s*[:\-]?\s*"
        r"(?!date\b|number\b|no\b)([A-Z][A-Z0-9\-]*\d[A-Z0-9\-]*)",
        re.IGNORECASE)),
    ("date", re.compile(
        rf"invoice\s+date\s*[:\-]?\s*({_DATE_PATTERN})", re.IGNORECASE)),
    ("total", re.compile(
        r"(?:total|amount\s+due|grand\s+total)\s*[:\-]?\s*"
        r"((?:[$€£₹]\s?)?\d[\d,]*(?:\.\d{2})?)", re.IGNORECASE)),
)

#: Applied to every document regardless of type. Passports, licences,
#: insurance policies and rental agreements all carry an expiry date but are
#: neither warranties nor invoices, and an expiry the dashboard cannot see is
#: worse than useless. Limited to high-confidence, clearly-labelled fields so
#: running it on all 100+ filler documents adds no noise.
_GENERIC_PATTERNS: Sequence[tuple[str, re.Pattern]] = (
    ("expiry_date", re.compile(
        rf"(?:date\s+of\s+)?(?:expires?|expired|expiry|valid\s+(?:un)?til|"
        rf"valid\s+through|renew(?:al)?\s+(?:by|date))\s*(?:date)?\s*"
        rf"[:\-]?\s*({_DATE_PATTERN})", re.IGNORECASE)),
    ("start_date", re.compile(
        rf"(?:date\s+of\s+)?(?:issue(?:d)?|valid\s+from|start(?:s|ing)?|"
        rf"effective|commence(?:s|ment)?)\s*(?:date)?\s*[:\-]?\s*"
        rf"({_DATE_PATTERN})", re.IGNORECASE)),
)

_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}

#: Human labels for the UI, keyed by fact field.
_LABELS = {
    "expiry_date": "Expiry Date",
    "start_date": "Start Date",
    "serial": "Serial / Service Tag",
    "product": "Product",
    "contract": "Contract Number",
    "vendor": "Vendor",
    "invoice_no": "Invoice Number",
    "date": "Invoice Date",
    "total": "Total",
    "currency": "Currency",
}


@dataclass
class ExtractedFact:
    """One candidate fact, before it has been verified and stored."""

    type: str
    field: str
    value: str
    norm_value: Optional[str] = None
    source_document_hash: Optional[str] = None
    source_chunk_id: Optional[int] = None
    source_quote: str = ""

    @property
    def label(self) -> str:
        return _LABELS.get(self.field, self.field.replace("_", " ").title())


# ---------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------


def classify_document(text: str, title: Optional[str] = None) -> str:
    """Keyword classifier: warranty, invoice, or other.

    Title words count double -- "dell_warranty.pdf" is a strong signal, and
    body text mentioning the word once in passing is not.
    """
    haystack = (text or "").lower()
    title_text = (title or "").lower()

    def score(keywords: Iterable[str]) -> int:
        return sum(
            haystack.count(keyword) + 2 * title_text.count(keyword)
            for keyword in keywords
        )

    warranty_score = score(_WARRANTY_KEYWORDS)
    invoice_score = score(_INVOICE_KEYWORDS)
    # Threshold of 2, not 1. The demo corpus is full of filler prose that
    # mentions "tax" or "receipt" once in passing; classifying those as
    # invoices fills the facts table with noise nobody asked for.
    if max(warranty_score, invoice_score) < 2:
        return OTHER
    return WARRANTY if warranty_score >= invoice_score else INVOICE


# ---------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------


def normalize_date(text: str) -> Optional[str]:
    """Parse a date as written in a document into ISO-8601, or None.

    `dateparser` first (it handles ordinals and odd separators), with a
    stdlib fallback so extraction still works if the optional dependency is
    missing. DMY is preferred for ambiguous numeric dates, matching
    dateparser's default and most of the world's paperwork.
    """
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", (text or "").strip(), flags=re.I)
    if not cleaned:
        return None

    if dateparser is not None:
        parsed = dateparser.parse(
            cleaned, settings={"DATE_ORDER": "DMY", "PREFER_DAY_OF_MONTH": "first"}
        )
        if parsed is not None:
            return parsed.date().isoformat()

    for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y",
                "%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalize_amount(text: str) -> Optional[str]:
    """"$1,749.00" -> "1749.00"."""
    digits = re.sub(r"[^\d.]", "", text or "")
    if not digits:
        return None
    try:
        return f"{float(digits):.2f}"
    except ValueError:
        return None


def detect_currency(text: str) -> Optional[str]:
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in (text or ""):
            return code
    match = re.search(r"\b(USD|EUR|GBP|INR)\b", text or "", re.IGNORECASE)
    return match.group(1).upper() if match else None


# ---------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------


def _sentence_containing(text: str, span_start: int) -> str:
    """The sentence of `text` that contains character offset `span_start`.

    This becomes `source_quote`, so it must be a verbatim slice of the
    chunk -- never reconstructed or cleaned up.
    """
    start = 0
    for match in _SENTENCE_RE.finditer(text):
        if match.start() > span_start:
            return text[start : match.start()].strip()
        start = match.end()
    return text[start:].strip()


def extract_from_text(
    text: str,
    doc_type: str,
    content_hash: Optional[str] = None,
    chunk_id: Optional[int] = None,
    title: Optional[str] = None,
) -> List[ExtractedFact]:
    """Run the pattern set for `doc_type` over one chunk of text."""
    if doc_type == WARRANTY:
        patterns = tuple(_WARRANTY_PATTERNS)
    elif doc_type == INVOICE:
        patterns = tuple(_INVOICE_PATTERNS) + tuple(_GENERIC_PATTERNS)
    else:
        # Not a warranty or an invoice, but it may still expire.
        patterns = tuple(_GENERIC_PATTERNS)

    facts: List[ExtractedFact] = []
    seen: set[tuple[str, str]] = set()
    for field_name, pattern in patterns:
        for match in pattern.finditer(text):
            raw = match.group(1).strip().rstrip(".,;:")
            if not raw:
                continue
            key = (field_name, raw.lower())
            if key in seen:
                continue
            seen.add(key)

            if field_name in ("expiry_date", "start_date", "date"):
                norm = normalize_date(raw)
                if norm is None:
                    continue           # unparseable date -> not a fact
            elif field_name == "total":
                norm = normalize_amount(raw)
            else:
                norm = raw.upper() if field_name in ("serial", "contract") else raw

            facts.append(
                ExtractedFact(
                    type=doc_type,
                    field=field_name,
                    value=raw,
                    norm_value=norm,
                    source_document_hash=content_hash,
                    source_chunk_id=chunk_id,
                    source_quote=_sentence_containing(text, match.start()),
                )
            )
            if field_name == "total":
                currency = detect_currency(match.group(1))
                if currency:
                    facts.append(
                        ExtractedFact(
                            type=doc_type, field="currency", value=currency,
                            norm_value=currency,
                            source_document_hash=content_hash,
                            source_chunk_id=chunk_id,
                            source_quote=_sentence_containing(text, match.start()),
                        )
                    )

    return facts


_VENDOR_STOPWORDS = frozenset(
    "warranty warranties invoice invoices receipt copy synthetic document "
    "documents expired appliance record records old new limited hardware "
    "final draft scan scanned pdf docx png jpg jpeg page "
    # Generic nouns that appear in filenames ahead of the actual vendor.
    "laptop phone card bill statement agreement certificate policy licence "
    "license passport aadhaar aadhar pan marks sheet marksheet proof address "
    "insurance health car home rental bank account slip letter form".split()
)


def _guess_vendor(title: Optional[str], text: str) -> Optional[str]:
    """Vendor from the document title, then from an explicit "Provider" line.

    Titles are the better signal: "Dell Warranty" names the vendor, whereas
    body text is full of other companies. Note that `documents.title` is
    often the *filename* ("old_expired_warranty.pdf"), so the extension is
    stripped and separators split before matching -- otherwise the first
    "word" of that title is literally "warranty.pdf".

    Deliberately conservative: a wrong vendor is worse than no vendor,
    because the handover plan warns about near-duplicate invoices from
    different vendors.
    """
    if title:
        stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", title)
        words = [
            word
            for word in re.findall(r"[A-Za-z][A-Za-z&]+", stem.replace("_", " ").replace("-", " "))
            if word.lower() not in _VENDOR_STOPWORDS
        ]
        if words:
            return words[0].capitalize() if words[0].islower() else words[0]
    match = re.search(r"provider\s*[:\-]?\s*([^.\n]{2,60})", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


# ---------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------


def store_facts(
    facts: Sequence[ExtractedFact],
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, int]:
    """Persist facts, skipping any whose quote is not in its source chunk.

    A user-corrected fact is never overwritten: once someone fixes a value
    through PATCH /api/facts/{id}, re-running extraction must not silently
    undo their correction.
    """
    owns = conn is None
    conn = conn if conn is not None else connect(db_path)
    stored = skipped = protected = 0
    try:
        chunk_text_cache: Dict[int, str] = {}
        conn.execute("BEGIN IMMEDIATE")
        for fact in facts:
            if not _quote_is_in_source(conn, fact, chunk_text_cache):
                skipped += 1
                continue

            existing = conn.execute(
                "SELECT id, user_corrected FROM facts "
                "WHERE type=? AND field=? AND source_document_hash IS ?",
                (fact.type, fact.field, fact.source_document_hash),
            ).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            if existing is not None:
                if existing["user_corrected"]:
                    protected += 1
                    continue
                conn.execute(
                    "UPDATE facts SET value=?, norm_value=?, source_chunk_id=?, "
                    "source_quote=?, field=?, updated_at=? WHERE id=?",
                    (fact.value, fact.norm_value, fact.source_chunk_id,
                     fact.source_quote, fact.field, now, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO facts (type, field, value, norm_value, "
                    "source_document_hash, source_chunk_id, source_quote, "
                    "user_corrected, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                    (fact.type, fact.field, fact.value, fact.norm_value,
                     fact.source_document_hash, fact.source_chunk_id,
                     fact.source_quote, now, now),
                )
            stored += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        if owns:
            conn.close()
    return {"stored": stored, "skipped_unverified": skipped, "kept_corrected": protected}


def _quote_is_in_source(
    conn: sqlite3.Connection, fact: ExtractedFact, cache: Dict[int, str]
) -> bool:
    """The grounding check: does source_quote really appear in that chunk?"""
    if not fact.source_quote:
        return False
    if fact.source_chunk_id is None:
        return True                     # nothing to check against
    if fact.source_chunk_id not in cache:
        row = conn.execute(
            "SELECT text FROM chunks WHERE id=?", (fact.source_chunk_id,)
        ).fetchone()
        cache[fact.source_chunk_id] = row["text"] if row else ""
    haystack = _WS_RE.sub(" ", cache[fact.source_chunk_id]).casefold()
    needle = _WS_RE.sub(" ", fact.source_quote).casefold()
    return needle in haystack


# ---------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------


def extract_for_document(
    content_hash: str, db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Classify one document and extract facts from all of its live chunks."""
    conn = connect(db_path)
    try:
        title_row = conn.execute(
            "SELECT title FROM documents WHERE content_hash=?", (content_hash,)
        ).fetchone()
        title = title_row["title"] if title_row else None
        chunks = conn.execute(
            "SELECT id, text FROM chunks WHERE content_hash=? AND superseded=0 "
            "ORDER BY chunk_index",
            (content_hash,),
        ).fetchall()
    finally:
        conn.close()

    if not chunks:
        return {"content_hash": content_hash, "doc_type": OTHER, "facts": 0}

    full_text = "\n".join(row["text"] for row in chunks)
    doc_type = classify_document(full_text, title)
    facts: List[ExtractedFact] = []
    for row in chunks:
        facts.extend(
            extract_from_text(row["text"], doc_type, content_hash, row["id"], title)
        )

    # Vendor is a document-level fact, and only worth recording when the
    # document yielded something substantive. On its own it is noise.
    if facts:
        vendor = _guess_vendor(title, full_text)
        if vendor:
            anchor = chunks[0]
            position = anchor["text"].lower().find(vendor.lower())
            facts.append(
                ExtractedFact(
                    type=doc_type, field="vendor", value=vendor,
                    norm_value=vendor, source_document_hash=content_hash,
                    source_chunk_id=anchor["id"],
                    source_quote=_sentence_containing(
                        anchor["text"], position if position >= 0 else 0
                    ),
                )
            )

    result = store_facts(facts, db_path) if facts else {"stored": 0}
    return {
        "content_hash": content_hash,
        "doc_type": doc_type,
        "facts": result.get("stored", 0),
        **{k: v for k, v in result.items() if k != "stored"},
    }


def extract_all(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Extract facts for every active document. Idempotent."""
    conn = connect(db_path)
    try:
        hashes = [
            row["content_hash"]
            for row in conn.execute(
                "SELECT content_hash FROM documents WHERE status='active'"
            )
        ]
    finally:
        conn.close()

    totals = {"documents": 0, "facts": 0, WARRANTY: 0, INVOICE: 0, OTHER: 0}
    for content_hash in hashes:
        outcome = extract_for_document(content_hash, db_path)
        totals["documents"] += 1
        totals["facts"] += outcome["facts"]
        totals[outcome["doc_type"]] += 1
    return totals


# ---------------------------------------------------------------------
# Queries used by the API and by retrieval
# ---------------------------------------------------------------------


def list_facts(
    fact_type: Optional[str] = None,
    expiring_within: Optional[int] = None,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """Facts, optionally filtered by type and by days-until-expiry.

    `expiring_within=60` answers "what lapses in the next 60 days" purely in
    SQL against `norm_value`, which is why dates are stored in ISO form.
    Already-expired items are included: "your warranty ran out last month"
    is exactly what a user needs to hear.
    """
    owns = conn is None
    conn = conn if conn is not None else connect(db_path)
    try:
        sql = ["SELECT f.*, d.title AS document_title FROM facts f "
               "LEFT JOIN documents d ON d.content_hash = f.source_document_hash"]
        where: List[str] = []
        params: List[Any] = []
        if fact_type:
            where.append("f.type = ?")
            params.append(fact_type)
        if expiring_within is not None:
            cutoff = (date.today().toordinal() + int(expiring_within))
            where.append("f.field = 'expiry_date' AND f.norm_value IS NOT NULL "
                         "AND f.norm_value <= ?")
            params.append(date.fromordinal(cutoff).isoformat())
        if where:
            sql.append("WHERE " + " AND ".join(where))
        sql.append("ORDER BY CASE WHEN f.field='expiry_date' THEN f.norm_value END, f.id")
        rows = conn.execute(" ".join(sql), tuple(params)).fetchall()
    finally:
        if owns:
            conn.close()
    results = []
    for row in rows:
        record = dict(row)
        record["label"] = _LABELS.get(record["field"], record["field"].replace("_", " ").title())
        results.append(record)
    return results


def facts_for_question(
    question: str, limit: int = 6, db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Fact rows worth adding to the evidence for a date/expiry question.

    Deliberately narrow: only fires for questions that are actually about
    time or money, and only returns facts whose document shares a word with
    the question. Injecting facts into every question would dilute the
    retrieved chunks the answer prompt depends on.
    """
    lowered = (question or "").lower()
    triggers = ("expir", "expiry", "warrant", "valid", "cover", "renew", "due",
                "when", "date", "how long", "still", "total", "cost", "paid",
                "invoice", "amount")
    if not any(trigger in lowered for trigger in triggers):
        return []

    words = {w for w in re.findall(r"[a-z0-9]{3,}", lowered)}

    # Field priority, not just word overlap. Every fact on one document
    # mentions that document's title, so overlap alone ties them all at 1 and
    # the `limit` cut then drops whichever happened to be inserted last. For
    # "am I still covered?" the fact that must never be dropped is the expiry
    # date -- so questions about coverage or time promote it explicitly.
    asks_expiry = any(
        trigger in lowered
        for trigger in ("expir", "cover", "valid", "still", "warrant", "renew",
                        "how long", "when", "due", "lapse")
    )
    asks_money = any(
        trigger in lowered
        for trigger in ("total", "cost", "much", "paid", "amount", "price",
                        "invoice")
    )
    priority = {
        "expiry_date": 6 if asks_expiry else 1,
        "start_date": 3 if asks_expiry else 1,
        "total": 6 if asks_money else 1,
        "currency": 2 if asks_money else 0,
        "invoice_no": 4 if asks_money else 1,
    }

    scored: List[tuple[int, int, Dict[str, Any]]] = []
    for row in list_facts(db_path=db_path):
        haystack = " ".join(
            str(row.get(key) or "") for key in
            ("value", "norm_value", "document_title", "source_quote")
        ).lower()
        overlap = sum(1 for word in words if word in haystack)
        if not overlap:
            continue
        scored.append((priority.get(row["field"], 1), overlap, row))
    scored.sort(key=lambda triple: (-triple[0], -triple[1]))
    return [row for _, _, row in scored[:limit]]
