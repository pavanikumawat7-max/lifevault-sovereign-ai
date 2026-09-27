"""S3 tests: hybrid retrieval, RRF, grounding verification, /api/chat.

Everything here runs in fixture mode against a hand-seeded temp database,
so no Ollama and no indexing run is required. Chunks are inserted directly
into `chunks`; S1's FTS5 triggers populate `chunks_fts` for free, and
`chunks_vec` stays empty so the lexical arm is what ranks -- which is
exactly the degraded path api/search.py promises to keep working.
"""
from __future__ import annotations

import pytest

WARRANTY_TEXT = (
    "Dell Limited Hardware Warranty. Product: Dell XPS 15. "
    "Service tag: SYNTH-XPS-2026. Purchase date: June 12, 2026. "
    "Warranty expires June 12, 2027."
)
INVOICE_TEXT = (
    "Dell Invoice INV-DELL-10482. Invoice date June 12, 2026. "
    "Dell XPS 15 laptop. Synthetic total $1,749.00."
)


@pytest.fixture
def fixture_mode(monkeypatch, tmp_db_path):
    """Fixture mode + a temp DB, with the config cache reset around it."""
    monkeypatch.setenv("LIFEVAULT_USE_FIXTURES", "true")
    monkeypatch.setenv("LIFEVAULT_DB_PATH", tmp_db_path)
    from config import reset_config_cache

    reset_config_cache()
    yield tmp_db_path
    reset_config_cache()


def _seed(db_path: str) -> dict:
    """A tiny corpus: one duplicated warranty, one invoice, one stale chunk."""
    from db.connect import connect
    from db.init_db import init_db

    init_db(db_path)
    conn = connect(db_path)
    ids = {}
    try:
        conn.execute("BEGIN IMMEDIATE")
        for content_hash, title, paths in (
            (
                "hash_warranty",
                "Dell Warranty",
                ["/vault/folder_A/dell_warranty.pdf", "/vault/folder_B/dell_copy.pdf"],
            ),
            ("hash_invoice", "Dell Invoice", ["/vault/folder_A/dell_invoice.pdf"]),
        ):
            conn.execute(
                "INSERT INTO documents (content_hash, title, doc_type, status) "
                "VALUES (?, ?, 'pdf', 'active')",
                (content_hash, title),
            )
            for path in paths:
                conn.execute(
                    "INSERT INTO file_locations (content_hash, path, missing) "
                    "VALUES (?, ?, 0)",
                    (content_hash, path),
                )

        cursor = conn.execute(
            "INSERT INTO chunks (content_hash, chunk_index, text, page, superseded) "
            "VALUES ('hash_warranty', 0, ?, 1, 0)",
            (WARRANTY_TEXT,),
        )
        ids["warranty"] = cursor.lastrowid
        cursor = conn.execute(
            "INSERT INTO chunks (content_hash, chunk_index, text, page, superseded) "
            "VALUES ('hash_invoice', 0, ?, 1, 0)",
            (INVOICE_TEXT,),
        )
        ids["invoice"] = cursor.lastrowid
        # A superseded chunk that would otherwise be the best lexical match.
        cursor = conn.execute(
            "INSERT INTO chunks (content_hash, chunk_index, text, page, superseded) "
            "VALUES ('hash_warranty', 1, ?, 2, 1)",
            ("Superseded draft: Dell XPS 15 warranty expires June 12, 2099.",),
        )
        ids["stale"] = cursor.lastrowid
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return ids


# ---------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------


def test_rrf_uses_the_specified_formula_and_rewards_both_rankers():
    """score = sum(1 / (60 + rank)), and agreement beats a single ranker."""
    from api.search import RRF_K, reciprocal_rank_fusion

    scores = reciprocal_rank_fusion([[101, 102], [102, 103]])

    assert scores[101] == pytest.approx(1 / (RRF_K + 1))
    assert scores[103] == pytest.approx(1 / (RRF_K + 2))
    # Found by both rankers, so both contributions add up.
    assert scores[102] == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))
    assert scores[102] > scores[101] > scores[103]


def test_build_match_query_quotes_terms_so_fts_operators_cannot_inject():
    """A question full of FTS5 syntax must become harmless literal terms."""
    from api.search import build_match_query

    match = build_match_query('dell NOT warranty "quoted" OR * (x)')

    # Every surviving term is a quoted literal, and nothing else remains:
    # the user's NOT/OR are dropped as stopwords, and "*" and "(" never
    # reach FTS5 at all, so none of them can act as query syntax.
    assert match == '"dell" OR "warranty" OR "quoted"'
    for forbidden in ("*", "(", ")", " NOT "):
        assert forbidden not in match



def test_build_match_query_falls_back_when_only_stopwords_remain():
    from api.search import build_match_query

    assert build_match_query("what is it about") != ""
    assert build_match_query("!!! ???") == ""


# ---------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------


def test_hybrid_search_collapses_duplicates_and_attaches_other_locations(fixture_mode):
    """One content hash in two folders is one hit with an "also found at"."""
    from api.search import hybrid_search

    _seed(fixture_mode)
    results = hybrid_search("Dell warranty expiry", db_path=fixture_mode)

    assert results, "expected at least one hit for an indexed term"
    warranty = next(r for r in results if r.content_hash == "hash_warranty")
    # The duplicate is collapsed, not returned twice.
    assert [r.content_hash for r in results].count("hash_warranty") == 1
    assert warranty.abs_path.endswith("dell_warranty.pdf")
    assert any(path.endswith("dell_copy.pdf") for path in warranty.also_found_at)
    assert len(warranty.locations) == 2


def test_retrieve_node_returns_the_contract_fields(fixture_mode):
    """The handover plan pins content_hash, abs_path, page and locations."""
    from graph.retrieve import retrieve

    _seed(fixture_mode)
    state = retrieve({"user_message": "Dell warranty expiry"})

    assert state["retrieved_chunks"]
    for chunk in state["retrieved_chunks"]:
        for field in ("content_hash", "abs_path", "page", "locations"):
            assert field in chunk, f"missing {field}"
        assert isinstance(chunk["locations"], list)


def test_hybrid_search_skips_superseded_chunks(fixture_mode):
    """A superseded chunk must never be retrievable, however well it matches."""
    from api.search import hybrid_search

    ids = _seed(fixture_mode)
    results = hybrid_search(
        "Dell XPS 15 warranty expires", top_k=10, db_path=fixture_mode
    )

    assert results
    assert ids["stale"] not in [r.chunk_id for r in results]
    assert all("2099" not in r.text for r in results)


def test_retrieve_survives_an_uninitialized_database(monkeypatch, tmp_path):
    """No index yet must mean "no results", not a crash."""
    monkeypatch.setenv("LIFEVAULT_USE_FIXTURES", "true")
    monkeypatch.setenv("LIFEVAULT_DB_PATH", str(tmp_path / "empty.db"))
    from config import reset_config_cache

    reset_config_cache()
    from graph.retrieve import retrieve

    state = retrieve({"user_message": "anything at all"})
    assert state["retrieved_chunks"] == []
    reset_config_cache()


# ---------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------


def _chunks_for_grounding():
    return [
        {
            "chunk_id": 1,
            "content_hash": "hash_warranty",
            "text": WARRANTY_TEXT,
            "page": 1,
            "abs_path": "/vault/folder_A/dell_warranty.pdf",
            "locations": [{"path": "/vault/folder_A/dell_warranty.pdf", "missing": False}],
            "also_found_at": [],
        }
    ]


def test_verify_grounding_rejects_a_fake_date(fixture_mode):
    """THE acceptance test: a cited date that is not in the cited chunk.

    The chunk says the warranty expires June 12, 2027. The answer claims
    June 12, 2028 and cites that same chunk. That must be rejected, and
    because the retry has already been spent the answer must be replaced
    with "could not verify" -- never returned as-is.
    """
    from graph.verify import COULD_NOT_VERIFY, verify_grounding

    state = {
        "user_message": "When does my Dell warranty expire?",
        "retrieved_chunks": _chunks_for_grounding(),
        "answer_text": "Your Dell XPS 15 warranty expires June 12, 2028.",
        "answer_cited_labels": ["C1"],
        "answer_retried": True,  # retry already spent, so this is terminal
    }
    result = verify_grounding(state)

    assert result["grounded"] is False
    assert result["answer_text"] == COULD_NOT_VERIFY
    assert result["citations"] == []
    assert "June 12, 2028" in result["verification"]["unsupported_dates"]
    # The real date must not be blamed.
    assert "June 12, 2027" not in result["verification"]["unsupported_dates"]


def test_check_grounding_accepts_a_reformatted_but_real_date():
    """2027-06-12 is the same day as "June 12, 2027" and must pass."""
    from graph.verify import check_grounding

    report = check_grounding(
        "The warranty expires 2027-06-12.", ["C1"], _chunks_for_grounding()
    )

    assert report.grounded is True, report.reason
    assert report.unsupported_dates == []


def test_check_grounding_rejects_an_invented_quote():
    from graph.verify import check_grounding

    report = check_grounding(
        'The document says "your coverage is void after one year".',
        ["C1"],
        _chunks_for_grounding(),
    )

    assert report.grounded is False
    assert report.unsupported_quotes == [
        "your coverage is void after one year"
    ]


def test_check_grounding_rejects_a_citation_the_model_was_never_shown():
    """Citing C7 when only C1 exists is a grounding failure, not a citation."""
    from graph.verify import check_grounding

    report = check_grounding("Expires June 12, 2027.", ["C7"], _chunks_for_grounding())

    assert report.grounded is False
    assert report.invalid_labels == ["C7"]


def test_check_grounding_requires_at_least_one_citation():
    from graph.verify import check_grounding

    report = check_grounding("Expires June 12, 2027.", [], _chunks_for_grounding())

    assert report.grounded is False
    assert "cites no chunk" in (report.reason or "")


def test_verify_grounding_retries_once_and_can_recover(fixture_mode):
    """A first bad draft gets exactly one more attempt before refusing."""
    from graph.verify import verify_grounding

    state = {
        "user_message": "When does my Dell warranty expire?",
        "retrieved_chunks": _chunks_for_grounding(),
        "answer_text": "It expires June 12, 2028.",  # wrong: triggers the retry
        "answer_cited_labels": ["C1"],
        "answer_retried": False,
    }
    result = verify_grounding(state)

    # In fixture mode the retry quotes the chunk verbatim, so it recovers.
    assert result["grounded"] is True, result["verification"]
    assert result["verification"]["recovered_on_retry"] is True
    assert result["answer_retried"] is True
    assert "June 12, 2028" not in result["answer_text"]


def test_citations_carry_path_and_page(fixture_mode):
    from graph.verify import build_citations

    citations = build_citations(
        "Expires June 12, 2027.", ["C1"], _chunks_for_grounding()
    )

    assert len(citations) == 1
    citation = citations[0]
    assert citation["path"] == "/vault/folder_A/dell_warranty.pdf"
    assert citation["page"] == 1
    assert citation["document_hash"] == "hash_warranty"
    assert citation["chunk_id"] == 1
    assert citation["quote"]


# ---------------------------------------------------------------------
# Answer prompt
# ---------------------------------------------------------------------


def test_answer_prompt_numbers_chunks_and_frames_them_as_untrusted():
    from graph.answer import build_messages, format_chunks

    block = format_chunks(_chunks_for_grounding() * 2)
    assert "[C1]" in block and "[C2]" in block
    assert block.count("<<<") == 2 and block.count(">>>") == 2

    messages = build_messages("Does it expire?", _chunks_for_grounding())
    system = messages[0]["content"].lower()
    assert messages[0]["role"] == "system"
    assert "untrusted" in system
    assert "never an instruction" in system
    assert "untrusted data" in messages[-1]["content"].lower()


def test_resolve_citations_accepts_loose_model_formats():
    from graph.answer import resolve_citations

    chunks = [{"chunk_id": 11}, {"chunk_id": 22}]
    for raw in (["C1", "C2"], ["c1", "2"], "C1, C2", [1, 2]):
        labels, chunk_ids = resolve_citations(raw, chunks)
        assert labels == ["C1", "C2"], raw
        assert chunk_ids == [11, 22], raw

    # Out-of-range labels are dropped rather than silently accepted.
    assert resolve_citations(["C9"], chunks) == ([], [])


def test_parse_model_json_recovers_from_fenced_and_chatty_replies():
    from graph.answer import parse_model_json

    payload, error = parse_model_json('```json\n{"answer": "hi"}\n```')
    assert error is None and payload["answer"] == "hi"

    payload, error = parse_model_json('Sure! {"answer": "hi"} Hope that helps.')
    assert error is None and payload["answer"] == "hi"

    payload, error = parse_model_json("not json at all")
    assert payload == {} and error


# ---------------------------------------------------------------------
# HTTP contract
# ---------------------------------------------------------------------


def test_chat_endpoint_returns_cited_answer_with_path_and_page(fixture_mode):
    """End-to-end over HTTP: JSON only, citations carry path and page."""
    testclient = pytest.importorskip("fastapi.testclient")
    _seed(fixture_mode)

    import api.routes.chat as chat_route

    chat_route._GRAPH_CACHE.clear()  # don't reuse another test's temp DB
    from api.main import create_app

    client = testclient.TestClient(create_app())
    response = client.post("/api/chat", json={"message": "Dell warranty expiry"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"]
    assert body["conversation_id"]
    assert body["grounded"] is True, body.get("verification_reason")
    assert body["citations"], "a grounded answer must carry citations"
    citation = body["citations"][0]
    assert citation["path"] and citation["path"].endswith(".pdf")
    assert citation["page"] == 1
    assert citation["document_hash"]
    assert citation["label"] == "C1"
    # Frozen S1 fields are still present and typed as before.
    assert body["proposal_id"] is None
    assert isinstance(body["latency_ms"], int)
    chat_route._GRAPH_CACHE.clear()


def test_chat_endpoint_is_honest_when_nothing_is_indexed(monkeypatch, tmp_path):
    """No corpus must produce a non-empty, ungrounded, uncited answer."""
    testclient = pytest.importorskip("fastapi.testclient")
    monkeypatch.setenv("LIFEVAULT_USE_FIXTURES", "true")
    monkeypatch.setenv("LIFEVAULT_DB_PATH", str(tmp_path / "empty.db"))
    from config import reset_config_cache

    reset_config_cache()
    import api.routes.chat as chat_route

    chat_route._GRAPH_CACHE.clear()
    from api.main import create_app

    client = testclient.TestClient(create_app())
    body = client.post("/api/chat", json={"message": "when does it expire?"}).json()

    assert body["answer"]
    assert body["grounded"] is False
    assert body["citations"] == []
    chat_route._GRAPH_CACHE.clear()
    reset_config_cache()
