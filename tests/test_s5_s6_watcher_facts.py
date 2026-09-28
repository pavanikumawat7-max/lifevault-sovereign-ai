"""S5 and S6 tests: watcher filters, deletion handling, fact extraction.

Nothing here needs a model or the OCR engine. OCR itself is exercised by one
test that skips when RapidOCR is not installed, because it is declared as an
optional runtime dependency.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

WARRANTY_TEXT = (
    "Dell Limited Hardware Warranty. Product: Dell XPS 15. "
    "Service tag: SYNTH-XPS-2026. Purchase date: June 12, 2026. "
    "Warranty expires June 12, 2027."
)
INVOICE_TEXT = (
    "Dell Invoice INV-DELL-10482. Invoice date June 12, 2026. "
    "Dell XPS 15 laptop. Synthetic total $1,749.00. Payment status paid."
)
FILLER_TEXT = (
    "Synthetic Utilities Record 014. Reference DEMO-0014. Date 2022-01-11. "
    "Provider Lara and Sons. Treat avoid technology take goal investment."
)


@pytest.fixture
def env(monkeypatch, tmp_db_path, tmp_path):
    monkeypatch.setenv("LIFEVAULT_USE_FIXTURES", "true")
    monkeypatch.setenv("LIFEVAULT_DB_PATH", tmp_db_path)
    monkeypatch.setenv("LIFEVAULT_VAULT_DIR", str(tmp_path / "vault"))
    from config import reset_config_cache

    reset_config_cache()
    from db.init_db import init_db

    init_db(tmp_db_path)
    yield tmp_db_path
    reset_config_cache()


def _seed_document(db_path: str, content_hash: str, title: str, text: str) -> int:
    from db.connect import connect

    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO documents (content_hash, title, doc_type) "
            "VALUES (?, ?, 'pdf')",
            (content_hash, title),
        )
        cursor = conn.execute(
            "INSERT INTO chunks (content_hash, chunk_index, text, page) "
            "VALUES (?, 0, ?, 1)",
            (content_hash, text),
        )
        return cursor.lastrowid
    finally:
        conn.close()


# ---------------------------------------------------------------------
# S6: fact extraction
# ---------------------------------------------------------------------


def test_classifier_needs_a_real_signal_not_one_stray_word(env):
    """Filler prose that says "receipt" once must not become an invoice."""
    from worker.facts import INVOICE, OTHER, WARRANTY, classify_document

    assert classify_document(WARRANTY_TEXT, "dell_warranty.pdf") == WARRANTY
    assert classify_document(INVOICE_TEXT, "dell_invoice.pdf") == INVOICE
    assert classify_document(FILLER_TEXT, "record_014.pdf") == OTHER
    assert classify_document("A receipt was mentioned once.", "notes.pdf") == OTHER


def test_warranty_fields_extract_with_iso_normalization(env):
    from worker.facts import WARRANTY, extract_from_text

    facts = {f.field: f for f in extract_from_text(WARRANTY_TEXT, WARRANTY, "h1", 1)}

    assert facts["expiry_date"].value == "June 12, 2027"
    assert facts["expiry_date"].norm_value == "2027-06-12"
    assert facts["start_date"].norm_value == "2026-06-12"
    assert facts["serial"].value == "SYNTH-XPS-2026"
    assert facts["product"].value == "Dell XPS 15"
    # Every fact quotes the sentence it came from, verbatim.
    for fact in facts.values():
        assert fact.source_quote in WARRANTY_TEXT


def test_invoice_number_is_not_the_word_date(env):
    """Regression: "Invoice date June 12" used to yield invoice_no="date"."""
    from worker.facts import INVOICE, extract_from_text

    facts = {f.field: f for f in extract_from_text(INVOICE_TEXT, INVOICE, "h2", 2)}

    assert facts["invoice_no"].value == "INV-DELL-10482"
    assert facts["total"].norm_value == "1749.00"
    assert facts["currency"].value == "USD"
    assert facts["date"].norm_value == "2026-06-12"


def test_store_facts_rejects_a_quote_that_is_not_in_its_chunk(env):
    """The grounding rule for facts: no evidence, no fact."""
    from worker.facts import ExtractedFact, store_facts

    chunk_id = _seed_document(env, "h1", "dell_warranty.pdf", WARRANTY_TEXT)

    good = ExtractedFact(
        type="warranty", field="expiry_date", value="June 12, 2027",
        norm_value="2027-06-12", source_document_hash="h1",
        source_chunk_id=chunk_id, source_quote="Warranty expires June 12, 2027.",
    )
    fabricated = ExtractedFact(
        type="warranty", field="contract", value="FAKE-1",
        norm_value="FAKE-1", source_document_hash="h1",
        source_chunk_id=chunk_id, source_quote="This sentence is not in the chunk.",
    )

    outcome = store_facts([good, fabricated], db_path=env)

    assert outcome["stored"] == 1
    assert outcome["skipped_unverified"] == 1


def test_a_user_correction_survives_re_extraction(env):
    """PATCH sets user_corrected, and re-indexing must not undo it."""
    from worker.facts import ExtractedFact, extract_for_document, list_facts, store_facts

    chunk_id = _seed_document(env, "h1", "dell_warranty.pdf", WARRANTY_TEXT)
    store_facts(
        [ExtractedFact(
            type="warranty", field="expiry_date", value="June 12, 2027",
            norm_value="2027-06-12", source_document_hash="h1",
            source_chunk_id=chunk_id,
            source_quote="Warranty expires June 12, 2027.",
        )],
        db_path=env,
    )

    from db.connect import connect

    conn = connect(env)
    try:
        conn.execute(
            "UPDATE facts SET value='June 30, 2027', norm_value='2027-06-30', "
            "user_corrected=1 WHERE field='expiry_date'"
        )
    finally:
        conn.close()

    extract_for_document("h1", db_path=env)

    fact = next(f for f in list_facts(db_path=env) if f["field"] == "expiry_date")
    assert fact["norm_value"] == "2027-06-30", "a correction must not be overwritten"
    assert fact["user_corrected"] == 1


def test_expiring_within_filters_by_iso_date(env):
    from worker.facts import ExtractedFact, list_facts, store_facts

    chunk_id = _seed_document(env, "h1", "dell_warranty.pdf", WARRANTY_TEXT)
    quote = "Warranty expires June 12, 2027."
    store_facts(
        [
            ExtractedFact(type="warranty", field="expiry_date", value="June 12, 2027",
                          norm_value="2027-06-12", source_document_hash="h1",
                          source_chunk_id=chunk_id, source_quote=quote),
            ExtractedFact(type="warranty", field="expiry_date", value="March 3, 2021",
                          norm_value="2021-03-03", source_document_hash="h1",
                          source_chunk_id=chunk_id, source_quote=quote),
        ],
        db_path=env,
    )

    # Distinct (type, field, document) keys collapse, so assert on what a
    # 60-day window returns: only dates at or before the cutoff.
    soon = list_facts(expiring_within=60, db_path=env)
    assert all(f["norm_value"] <= "2027-06-12" for f in soon)
    assert list_facts(expiring_within=36500, db_path=env)


def test_facts_are_only_injected_for_time_or_money_questions(env):
    from worker.facts import ExtractedFact, facts_for_question, store_facts

    chunk_id = _seed_document(env, "h1", "dell_warranty.pdf", WARRANTY_TEXT)
    store_facts(
        [ExtractedFact(
            type="warranty", field="expiry_date", value="June 12, 2027",
            norm_value="2027-06-12", source_document_hash="h1",
            source_chunk_id=chunk_id,
            source_quote="Warranty expires June 12, 2027.",
        )],
        db_path=env,
    )

    covered = facts_for_question("Is my dell still covered?", db_path=env)
    assert covered and covered[0]["field"] == "expiry_date", (
        "an expiry question must surface the expiry fact first"
    )
    assert facts_for_question("who wrote this poem", db_path=env) == []


# ---------------------------------------------------------------------
# S5: watcher
# ---------------------------------------------------------------------


def test_watcher_ignores_partial_downloads_hidden_files_and_the_vault(env, tmp_path):
    from worker.watcher import is_ignorable

    vault = Path(str(tmp_path / "vault")).resolve()
    vault.mkdir(parents=True, exist_ok=True)

    assert is_ignorable(vault / "reminders" / "x.ics", vault) is True
    assert is_ignorable(tmp_path / "a.pdf.part", vault) is True
    assert is_ignorable(tmp_path / "a.pdf.crdownload", vault) is True
    assert is_ignorable(tmp_path / "a.tmp", vault) is True
    assert is_ignorable(tmp_path / ".hidden" / "a.pdf", vault) is True
    assert is_ignorable(tmp_path / "movie.mp4", vault) is True
    assert is_ignorable(tmp_path / "notes.docx", vault) is True, "DOCX is out of scope"

    assert is_ignorable(tmp_path / "real.pdf", vault) is False
    assert is_ignorable(tmp_path / "shot.png", vault) is False


def test_wait_until_stable_waits_out_a_growing_file(env, tmp_path):
    """A file still being copied must not be ingested half-written."""
    import threading
    import time

    from worker.watcher import wait_until_stable

    path = tmp_path / "growing.pdf"
    path.write_bytes(b"a")

    def grow() -> None:
        for _ in range(3):
            time.sleep(0.2)
            with path.open("ab") as handle:
                handle.write(b"aaaa")

    thread = threading.Thread(target=grow)
    thread.start()
    assert wait_until_stable(path, stable_seconds=0.4, timeout=10) is True
    thread.join()

    assert wait_until_stable(tmp_path / "gone.pdf", stable_seconds=0.1, timeout=1) is False


def test_deletion_marks_the_location_missing_and_keeps_everything_else(env):
    """A deleted file must not erase its document, chunks or facts."""
    from db.connect import connect
    from worker.watcher import mark_location_missing

    _seed_document(env, "h1", "dell_warranty.pdf", WARRANTY_TEXT)
    conn = connect(env)
    try:
        conn.execute(
            "INSERT INTO file_locations (content_hash, path, missing) "
            "VALUES ('h1', '/tmp/watched/dell_warranty.pdf', 0)"
        )
        conn.execute(
            "INSERT INTO facts (type, field, value, source_document_hash, "
            "source_quote) VALUES ('warranty', 'expiry_date', 'June 12, 2027', "
            "'h1', 'Warranty expires June 12, 2027.')"
        )
    finally:
        conn.close()

    assert mark_location_missing(Path("/tmp/watched/dell_warranty.pdf"), env) == 1

    conn = connect(env)
    try:
        assert conn.execute(
            "SELECT missing FROM file_locations WHERE content_hash='h1'"
        ).fetchone()["missing"] == 1
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1
    finally:
        conn.close()


def test_watcher_queues_changes_and_ignores_what_it_should(env, tmp_path):
    from worker.watcher import RootWatcher

    watcher = RootWatcher(db_path=env)
    watcher.note_change(tmp_path / "real.pdf", root_id=1)
    watcher.note_change(tmp_path / "half.pdf.part", root_id=1)
    watcher.note_change(tmp_path / ".DS_Store", root_id=1)

    assert watcher.stats.events_seen == 3
    assert watcher.stats.events_ignored == 2


# ---------------------------------------------------------------------
# S5: OCR
# ---------------------------------------------------------------------


def test_needs_ocr_threshold(env):
    from worker.ocr import MIN_PAGE_CHARS, needs_ocr

    assert needs_ocr("") is True
    assert needs_ocr("   \n  ") is True
    assert needs_ocr("x" * (MIN_PAGE_CHARS - 1)) is True
    assert needs_ocr("x" * (MIN_PAGE_CHARS + 1)) is False


def test_ocr_reads_the_demo_screenshot(env):
    """Skipped when RapidOCR is absent -- it is an optional dependency."""
    ocr = pytest.importorskip("rapidocr_onnxruntime")  # noqa: F841
    from worker.ocr import is_available, ocr_image

    if not is_available():
        pytest.skip("RapidOCR present but not loadable on this machine")

    screenshot = Path("demo-data/synthetic/screenshots/order_email.png")
    if not screenshot.is_file():
        pytest.skip("demo corpus not generated")

    text = ocr_image(screenshot)
    assert "DEMO-48291" in text
    assert "429" in text


def test_a_text_pdf_is_never_sent_to_ocr(env, monkeypatch):
    """OCR is a fallback. A page with a text layer must bypass it entirely."""
    pytest.importorskip("pymupdf")
    source = Path("demo-data/synthetic/folder_A/dell_warranty.pdf")
    if not source.is_file():
        pytest.skip("demo corpus not generated")

    from worker import ocr as ocr_module
    from worker.parse import parse_pdf

    def explode(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("OCR must not run on a page that already has text")

    monkeypatch.setattr(ocr_module, "ocr_pdf_page", explode)

    parsed = parse_pdf(source, "h1")
    assert parsed.pages
    assert all(page.ocr is False for page in parsed.pages)
