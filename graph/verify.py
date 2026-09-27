"""Grounding verification (S3).

The contract: an answer is published only if every date and every quoted
phrase in it actually appears in a chunk the answer cites. If that fails,
the answer is regenerated once with the failure reason fed back to the
model; if it fails again the answer is replaced with "could not verify".
An unsupported answer is never returned silently.

What gets checked, against the CITED chunks only (not everything
retrieved -- citing C1 and taking the date from C4 is a grounding failure):

  1. every cited label refers to a chunk the model was actually shown;
  2. at least one chunk is cited, when chunks were available;
  3. every date in the answer matches a date in the cited chunks --
     semantically, not just textually, so "2027-06-12" is accepted against
     "June 12, 2027" but "June 12, 2028" is rejected;
  4. every double-quoted phrase in the answer appears verbatim (modulo
     whitespace and case) in the cited chunks.

Why the retry lives here and not in the graph: the S1 graph topology is
pinned (retrieve -> answer -> verify_grounding -> propose_action, no back
edge), so adding a retry loop would change the graph's shape. This node
calls graph.answer.generate_answer() again itself instead, which keeps the
topology untouched and the retry cap at exactly one.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from graph import answer as answer_module
from graph.state import LifeVaultState

#: The literal reply required by the handover plan when grounding fails.
COULD_NOT_VERIFY = "could not verify"

_WS_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")

#: Straight and curly DOUBLE quotes only. Straight single quotes are
#: deliberately excluded: apostrophes ("don't", "Dell's") would otherwise
#: be parsed as quote delimiters and fail verification against text that
#: does support the answer.
_QUOTE_RES = (
    re.compile(r'"([^"\n]{3,300})"'),
    re.compile(r"“([^”\n]{3,300})”"),
    re.compile(r"‘([^’\n]{3,300})’"),
)

_MONTHS = {
    name.lower(): number
    for number, name in enumerate(calendar.month_name)
    if name
}
_MONTHS.update(
    {
        name.lower(): number
        for number, name in enumerate(calendar.month_abbr)
        if name
    }
)
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))

_MONTH_DAY_YEAR_RE = re.compile(
    rf"\b({_MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b",
    re.IGNORECASE,
)
_DAY_MONTH_YEAR_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_PATTERN})\.?,?\s+(\d{{4}})\b",
    re.IGNORECASE,
)
_ISO_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_NUMERIC_RE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
_MONTH_YEAR_RE = re.compile(
    rf"\b({_MONTH_PATTERN})\.?,?\s+(\d{{4}})\b", re.IGNORECASE
)
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2}|21\d{2})\b")

#: (year, month, day); month/day may be None when the text was less specific.
DateCandidate = Tuple[int, Optional[int], Optional[int]]


@dataclass(frozen=True)
class DateRef:
    """One date mentioned in some text, with every reading it could have.

    `candidates` holds more than one entry only for genuinely ambiguous
    forms such as 06/12/2027, which is accepted if *either* reading is
    supported -- the point is to catch invented dates, not to punish a
    model for locale.
    """

    text: str
    candidates: Tuple[DateCandidate, ...]


@dataclass
class GroundingReport:
    """Why an answer was accepted or rejected."""

    grounded: bool
    reason: Optional[str] = None
    cited_labels: List[str] = field(default_factory=list)
    invalid_labels: List[str] = field(default_factory=list)
    checked_dates: List[str] = field(default_factory=list)
    unsupported_dates: List[str] = field(default_factory=list)
    checked_quotes: List[str] = field(default_factory=list)
    unsupported_quotes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grounded": self.grounded,
            "reason": self.reason,
            "cited_labels": list(self.cited_labels),
            "invalid_labels": list(self.invalid_labels),
            "checked_dates": list(self.checked_dates),
            "unsupported_dates": list(self.unsupported_dates),
            "checked_quotes": list(self.checked_quotes),
            "unsupported_quotes": list(self.unsupported_quotes),
        }


# ---------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------


def extract_dates(text: str) -> List[DateRef]:
    """Every date-like mention in `text`, most specific forms first.

    Spans already consumed by a more specific pattern are not re-matched,
    so "June 12, 2027" yields one full date rather than also a month-year
    and a bare year.
    """
    refs: List[DateRef] = []
    consumed: List[Tuple[int, int]] = []

    def claim(start: int, end: int) -> bool:
        if any(start < used_end and end > used_start for used_start, used_end in consumed):
            return False
        consumed.append((start, end))
        return True

    for match in _MONTH_DAY_YEAR_RE.finditer(text):
        if claim(*match.span()):
            month = _MONTHS[match.group(1).lower()]
            refs.append(
                DateRef(match.group(0), ((int(match.group(3)), month, int(match.group(2))),))
            )
    for match in _DAY_MONTH_YEAR_RE.finditer(text):
        if claim(*match.span()):
            month = _MONTHS[match.group(2).lower()]
            refs.append(
                DateRef(match.group(0), ((int(match.group(3)), month, int(match.group(1))),))
            )
    for match in _ISO_RE.finditer(text):
        if claim(*match.span()):
            refs.append(
                DateRef(
                    match.group(0),
                    ((int(match.group(1)), int(match.group(2)), int(match.group(3))),),
                )
            )
    for match in _NUMERIC_RE.finditer(text):
        if claim(*match.span()):
            first, second, year = (int(group) for group in match.groups())
            # Ambiguous: accept both D/M/Y and M/D/Y readings.
            candidates = {(year, second, first), (year, first, second)}
            refs.append(DateRef(match.group(0), tuple(sorted(candidates))))
    for match in _MONTH_YEAR_RE.finditer(text):
        if claim(*match.span()):
            month = _MONTHS[match.group(1).lower()]
            refs.append(DateRef(match.group(0), ((int(match.group(2)), month, None),)))
    for match in _YEAR_RE.finditer(text):
        if claim(*match.span()):
            refs.append(DateRef(match.group(0), ((int(match.group(1)), None, None),)))
    return refs


def extract_quotes(text: str) -> List[str]:
    """Every double-quoted phrase in `text`, de-duplicated."""
    quotes: List[str] = []
    seen: Set[str] = set()
    for pattern in _QUOTE_RES:
        for match in pattern.finditer(text):
            phrase = match.group(1).strip()
            key = _normalize(phrase)
            if phrase and key not in seen:
                seen.add(key)
                quotes.append(phrase)
    return quotes


# ---------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------


def dates_compatible(left: DateCandidate, right: DateCandidate) -> bool:
    """Do two readings describe the same date, allowing missing parts?

    The year must always agree. A missing month or day on either side is a
    wildcard, so ("2027", None, None) is supported by (2027, 6, 12) -- the
    answer simply said less than the document did.
    """
    if left[0] != right[0]:
        return False
    for index in (1, 2):
        if left[index] is not None and right[index] is not None:
            if left[index] != right[index]:
                return False
    return True


def check_grounding(
    answer_text: str,
    cited_labels: Sequence[str],
    chunks: Sequence[Dict[str, Any]],
) -> GroundingReport:
    """Verify `answer_text` against the chunks it cites."""
    label_to_chunk = {
        answer_module.chunk_label(index): chunk for index, chunk in enumerate(chunks)
    }
    valid_labels = [label for label in cited_labels if label in label_to_chunk]
    invalid_labels = [label for label in cited_labels if label not in label_to_chunk]

    if invalid_labels:
        return GroundingReport(
            grounded=False,
            reason=(
                "answer cites "
                + ", ".join(invalid_labels)
                + ", which was not among the retrieved chunks"
            ),
            cited_labels=valid_labels,
            invalid_labels=invalid_labels,
        )
    if not valid_labels:
        return GroundingReport(
            grounded=False,
            reason="answer cites no chunk, so nothing supports it",
        )

    evidence = "\n\n".join(
        str(label_to_chunk[label].get("text", "")) for label in valid_labels
    )
    evidence_normalized = _normalize(evidence)
    evidence_dates = [
        candidate
        for ref in extract_dates(evidence)
        for candidate in ref.candidates
    ]

    unsupported_dates: List[str] = []
    checked_dates: List[str] = []
    for ref in extract_dates(answer_text):
        checked_dates.append(ref.text)
        # Verbatim presence is enough; otherwise fall back to a semantic
        # match so a legitimate reformatting is not treated as invention.
        if _normalize(ref.text) in evidence_normalized:
            continue
        if any(
            dates_compatible(candidate, evidence_date)
            for candidate in ref.candidates
            for evidence_date in evidence_dates
        ):
            continue
        unsupported_dates.append(ref.text)

    unsupported_quotes: List[str] = []
    checked_quotes: List[str] = []
    for phrase in extract_quotes(answer_text):
        checked_quotes.append(phrase)
        if _normalize(phrase) not in evidence_normalized:
            unsupported_quotes.append(phrase)

    problems: List[str] = []
    if unsupported_dates:
        problems.append(
            "date(s) not found in the cited chunks: "
            + ", ".join(repr(value) for value in unsupported_dates)
        )
    if unsupported_quotes:
        problems.append(
            "quoted phrase(s) not found in the cited chunks: "
            + ", ".join(repr(value) for value in unsupported_quotes)
        )

    return GroundingReport(
        grounded=not problems,
        reason="; ".join(problems) or None,
        cited_labels=valid_labels,
        checked_dates=checked_dates,
        unsupported_dates=unsupported_dates,
        checked_quotes=checked_quotes,
        unsupported_quotes=unsupported_quotes,
    )


def build_citations(
    answer_text: str,
    cited_labels: Sequence[str],
    chunks: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Citation payloads for the cited chunks, with path and page attached."""
    label_to_chunk = {
        answer_module.chunk_label(index): chunk for index, chunk in enumerate(chunks)
    }
    citations: List[Dict[str, Any]] = []
    for label in cited_labels:
        chunk = label_to_chunk.get(label)
        if chunk is None:
            continue
        citations.append(
            {
                "label": label,
                "document_hash": chunk.get("content_hash", ""),
                "chunk_id": chunk.get("chunk_id"),
                "quote": _supporting_quote(answer_text, str(chunk.get("text", ""))),
                "path": chunk.get("abs_path"),
                "page": chunk.get("page"),
                "also_found_at": list(chunk.get("also_found_at") or []),
            }
        )
    return citations


# ---------------------------------------------------------------------
# Graph node
# ---------------------------------------------------------------------


def is_refusal(answer_text: str) -> bool:
    """Did the model already decline to answer?"""
    normalized = _normalize(answer_text)
    return (
        normalized.startswith(COULD_NOT_VERIFY)
        or normalized == _normalize(answer_module.NO_DOCUMENTS_ANSWER)
    )


def verify_grounding(state: LifeVaultState) -> dict:
    """The `verify_grounding` node: check, retry once, or refuse."""
    chunks = list(state.get("retrieved_chunks") or [])
    answer_text = state.get("answer_text") or ""
    labels = list(state.get("answer_cited_labels") or [])

    if not chunks:
        return _unverified(
            answer_text or answer_module.NO_DOCUMENTS_ANSWER,
            reason="no documents were retrieved for this question",
            replace_answer=False,
        )
    if is_refusal(answer_text):
        return _unverified(
            answer_text,
            reason="the model reported that the documents do not answer this",
            replace_answer=False,
        )

    report = check_grounding(answer_text, labels, chunks)
    if report.grounded:
        return _verified(state, answer_text, report, chunks)

    # One retry, with the specific failure handed back to the model.
    if not state.get("answer_retried"):
        retry = answer_module.generate_answer(
            question=state.get("user_message") or "",
            chunks=chunks,
            history=state.get("history") or [],
            feedback=answer_module.RETRY_FEEDBACK.format(reason=report.reason or "unknown"),
            retried=True,
        )
        update = retry.to_state()
        if is_refusal(retry.answer):
            update.update(
                _unverified(
                    retry.answer,
                    reason="the model reported that the documents do not answer this",
                    replace_answer=False,
                    first_failure=report,
                )
            )
            return update
        retry_report = check_grounding(retry.answer, retry.cited_labels, chunks)
        if retry_report.grounded:
            update.update(_verified(state, retry.answer, retry_report, chunks))
            update["verification"]["recovered_on_retry"] = True
            update["verification"]["first_failure"] = report.reason
            return update
        update.update(
            _unverified(
                COULD_NOT_VERIFY,
                reason=retry_report.reason,
                replace_answer=True,
                first_failure=report,
                final_report=retry_report,
            )
        )
        return update

    return _unverified(
        COULD_NOT_VERIFY,
        reason=report.reason,
        replace_answer=True,
        final_report=report,
    )


def _verified(
    state: LifeVaultState,
    answer_text: str,
    report: GroundingReport,
    chunks: Sequence[Dict[str, Any]],
) -> dict:
    verification = report.to_dict()
    verification["recovered_on_retry"] = False
    return {
        "answer_text": answer_text,
        "grounded": True,
        "citations": build_citations(answer_text, report.cited_labels, chunks),
        "verification": verification,
    }


def _unverified(
    answer_text: str,
    reason: Optional[str],
    replace_answer: bool,
    first_failure: Optional[GroundingReport] = None,
    final_report: Optional[GroundingReport] = None,
) -> dict:
    verification = (final_report or GroundingReport(grounded=False)).to_dict()
    verification["grounded"] = False
    verification["reason"] = reason
    verification["replaced_answer"] = replace_answer
    if first_failure is not None:
        verification["first_failure"] = first_failure.reason
    return {
        "answer_text": answer_text,
        "grounded": False,
        # No citations on an answer we will not vouch for.
        "citations": [],
        "verification": verification,
    }


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _supporting_quote(answer_text: str, chunk_text: str, max_chars: int = 300) -> str:
    """The sentence of `chunk_text` that best supports `answer_text`."""
    sentences = [s.strip() for s in _SENTENCE_RE.split(chunk_text) if s.strip()]
    if not sentences:
        return chunk_text[:max_chars].strip()
    answer_words = set(_WORD_RE.findall(answer_text.lower()))
    best = max(
        sentences,
        key=lambda sentence: len(
            answer_words & set(_WORD_RE.findall(sentence.lower()))
        ),
    )
    return best[:max_chars].strip()


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip().casefold()
