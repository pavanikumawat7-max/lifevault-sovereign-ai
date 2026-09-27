#!/usr/bin/env python3
"""S3 retrieval/answer evaluation harness.

Runs a fixed question set through the real S3 path -- hybrid_search ->
answer -> verify_grounding -- and prints a results table with per-answer
latency. Use it to compare models:

    LIFEVAULT_USE_FIXTURES=false python scripts/eval.py
    LIFEVAULT_USE_FIXTURES=false python scripts/eval.py --model mistral:7b
    python scripts/eval.py --markdown docs/eval_S3.md --json docs/eval_S3.json

Honest by construction:

  * The model is warmed with a throwaway call before timing starts, and the
    warmup is reported separately. A cold Ollama load on an 8 GB laptop
    takes tens of seconds and would otherwise be charged to question 1.
  * Every question carries what a correct answer must contain and which
    file it must come from, so "cited" is checked against the expected
    source rather than just counted.
  * Question 10 has no answer in the corpus. Refusing it is the pass
    condition -- an eval that only rewards answering rewards making things
    up.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import llm  # noqa: E402
from config import get_config  # noqa: E402
from graph import answer as answer_module  # noqa: E402
from graph import verify as verify_module  # noqa: E402
from graph.retrieve import retrieve_chunks  # noqa: E402

#: Expected answers and sources come from demo-data/synthetic, which is
#: generated deterministically by scripts/generate_demo_corpus.py.
QUESTIONS: List[Dict[str, Any]] = [
    {
        "id": 1,
        "question": "When does my Dell laptop warranty expire?",
        "expect_contains": [["June 12, 2027", "2027-06-12"]],
        "expect_file": "dell_warranty.pdf",
    },
    {
        "id": 2,
        "question": "What is the service tag of my Dell XPS 15?",
        "expect_contains": ["SYNTH-XPS-2026"],
        "expect_file": "dell_warranty.pdf",
    },
    {
        "id": 3,
        "question": "How much did the Dell XPS 15 laptop cost?",
        "expect_contains": [["1,749.00", "1749.00"]],
        "expect_file": "dell_invoice.pdf",
    },
    {
        "id": 4,
        "question": "What is the invoice number for the Dell laptop?",
        "expect_contains": ["INV-DELL-10482"],
        "expect_file": "dell_invoice.pdf",
    },
    {
        "id": 5,
        "question": "On what date was the Dell XPS 15 purchased?",
        "expect_contains": [["June 12, 2026", "2026-06-12"]],
        "expect_file": "dell_warranty.pdf",
    },
    {
        "id": 6,
        "question": "Which warranty has already expired, and on what date?",
        "expect_contains": [["March 3, 2021", "2021-03-03"]],
        "expect_file": "old_expired_warranty.pdf",
    },
    {
        "id": 7,
        "question": "What is the contract number on the expired refrigerator warranty?",
        "expect_contains": ["OLD-DEMO-319"],
        "expect_file": "old_expired_warranty.pdf",
    },
    {
        "id": 8,
        "question": "Who is the provider on synthetic insurance record 001?",
        "expect_contains": ["Willis PLC"],
        "expect_file": "record_001.pdf",
    },
    {
        "id": 9,
        "question": "What is the reference number on the synthetic travel record 003?",
        "expect_contains": ["DEMO-0003"],
        "expect_file": "record_003.pdf",
    },
    {
        # Nothing in the corpus answers this. Refusing is the pass condition.
        "id": 10,
        "question": "What is my passport number and when does it expire?",
        "expect_contains": [],
        "expect_file": None,
        "expect_refusal": True,
    },
]


def _answer_contains(answer_text: str, expected: Any) -> bool:
    """Is `expected` present in the answer?

    An entry may be a string, or a list of equivalent spellings of the same
    fact -- any one of which counts. Dates need this: verify_grounding
    accepts "2026-06-12" as grounded against "June 12, 2026" (same date,
    different format), so the eval must not mark that correct answer wrong.
    """
    haystack = (answer_text or "").lower()
    variants = expected if isinstance(expected, (list, tuple)) else [expected]
    return any(str(variant).lower() in haystack for variant in variants)


def _describe_expected(expected: Any) -> str:
    if isinstance(expected, (list, tuple)):
        return " | ".join(str(variant) for variant in expected)
    return str(expected)


def run_question(item: Dict[str, Any], model: Optional[str]) -> Dict[str, Any]:
    """Run one question through retrieve -> answer -> verify, timed."""
    question = item["question"]
    started = time.perf_counter()

    chunks = retrieve_chunks(question)
    retrieval_ms = int((time.perf_counter() - started) * 1000)

    draft = answer_module.generate_answer(question, chunks, model=model)
    state: Dict[str, Any] = {
        "user_message": question,
        "retrieved_chunks": chunks,
        "history": [],
        **draft.to_state(),
    }
    state.update(verify_module.verify_grounding(state))
    latency_ms = int((time.perf_counter() - started) * 1000)

    answer_text = state.get("answer_text") or ""
    citations = state.get("citations") or []
    cited_files = [Path(c["path"]).name for c in citations if c.get("path")]
    refused = verify_module.is_refusal(answer_text)

    expected_file = item.get("expect_file")
    cited_expected = bool(expected_file) and expected_file in cited_files
    missing = [
        _describe_expected(expected)
        for expected in item.get("expect_contains", [])
        if not _answer_contains(answer_text, expected)
    ]

    if item.get("expect_refusal"):
        passed = refused
    else:
        passed = bool(state.get("grounded")) and not missing and cited_expected

    return {
        "id": item["id"],
        "question": question,
        "answer": answer_text,
        "grounded": bool(state.get("grounded")),
        "refused": refused,
        "confidence": state.get("confidence", 0.0),
        "model": state.get("answer_model") or (model or get_config().model_name),
        "retrieved": len(chunks),
        "citations": [
            {
                "label": c.get("label"),
                "document_hash": c.get("document_hash"),
                "chunk_id": c.get("chunk_id"),
                "path": c.get("path"),
                "page": c.get("page"),
                "also_found_at": c.get("also_found_at") or [],
            }
            for c in citations
        ],
        "cited_files": cited_files,
        "expect_file": expected_file,
        "cited_expected_file": cited_expected,
        "missing_expected_values": missing,
        "verification_reason": (state.get("verification") or {}).get("reason"),
        "retrieval_ms": retrieval_ms,
        "latency_ms": latency_ms,
        "pass": passed,
    }


def render_markdown(results: List[Dict[str, Any]], meta: Dict[str, Any]) -> str:
    """The results table, as the handover gate asks for."""
    lines: List[str] = []
    lines.append("# S3 evaluation results")
    lines.append("")
    lines.append(f"- Model: `{meta['model']}`")
    lines.append(f"- Embedding model: `{meta['embedding_model']}`")
    lines.append(f"- Fixture mode: `{meta['use_fixtures']}`")
    lines.append(f"- Chunks per answer (top_k): {meta['top_k']}")
    lines.append(f"- Corpus: {meta['documents']} documents / {meta['chunks']} chunks")
    lines.append(f"- Machine: {meta['machine']}")
    lines.append(f"- Warmup call (not counted): {meta['warmup_s']}")
    lines.append(f"- Run at: {meta['ran_at']}")
    lines.append("")
    passed = sum(1 for r in results if r["pass"])
    latencies = [r["latency_ms"] / 1000 for r in results]
    lines.append(
        f"**{passed}/{len(results)} passed** | "
        f"grounded {sum(1 for r in results if r['grounded'])}/{len(results)} | "
        f"cited the expected file "
        f"{sum(1 for r in results if r['cited_expected_file'])}"
        f"/{sum(1 for r in results if r['expect_file'])} | "
        f"latency median {statistics.median(latencies):.1f}s, "
        f"mean {statistics.fmean(latencies):.1f}s, "
        f"max {max(latencies):.1f}s"
    )
    lines.append("")
    lines.append(
        "| # | Question | Answer | Grounded | Cited | Source (path:page) | Expected file | Pass | Latency |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for result in results:
        sources = (
            "<br>".join(
                f"`{Path(c['path']).name}`:{c['page']}"
                for c in result["citations"]
                if c.get("path")
            )
            or "--"
        )
        labels = ", ".join(c["label"] or "?" for c in result["citations"]) or "--"
        lines.append(
            "| {id} | {question} | {answer} | {grounded} | {labels} | {sources} | "
            "{expected} | {passed} | {latency:.1f}s |".format(
                id=result["id"],
                question=_cell(result["question"]),
                answer=_cell(result["answer"], 90),
                grounded="yes" if result["grounded"] else "no",
                labels=labels,
                sources=sources,
                expected=f"`{result['expect_file']}`" if result["expect_file"] else "(none)",
                passed="PASS" if result["pass"] else "FAIL",
                latency=result["latency_ms"] / 1000,
            )
        )
    lines.append("")
    failures = [r for r in results if not r["pass"]]
    if failures:
        lines.append("## Failures")
        lines.append("")
        for result in failures:
            lines.append(f"- **Q{result['id']}** {result['question']}")
            lines.append(f"  - answer: {result['answer']!r}")
            if result["missing_expected_values"]:
                lines.append(
                    f"  - missing expected value(s): {result['missing_expected_values']}"
                )
            if result["expect_file"] and not result["cited_expected_file"]:
                lines.append(
                    f"  - expected `{result['expect_file']}`, cited {result['cited_files']}"
                )
            if result["verification_reason"]:
                lines.append(f"  - verification: {result['verification_reason']}")
        lines.append("")
    return "\n".join(lines)


def _cell(text: str, limit: int = 70) -> str:
    """Make a string safe for one markdown table cell."""
    flat = " ".join((text or "").split())
    if len(flat) > limit:
        flat = flat[: limit - 3] + "..."
    return flat.replace("|", "\\|")


def _corpus_counts() -> tuple[int, int]:
    from db.connect import connect

    conn = connect()
    try:
        documents = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunks = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE superseded = 0"
        ).fetchone()[0]
        return documents, chunks
    except Exception:  # noqa: BLE001 - an un-indexed DB is reportable, not fatal
        return 0, 0
    finally:
        conn.close()


def _machine() -> str:
    import platform

    return f"{platform.system()} {platform.machine()} (python {platform.python_version()})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="override the configured chat model")
    parser.add_argument("--limit", type=int, help="run only the first N questions")
    parser.add_argument("--json", type=Path, help="write raw results here")
    parser.add_argument("--markdown", type=Path, help="write the results table here")
    parser.add_argument(
        "--no-warmup",
        action="store_true",
        help="skip the warmup call (question 1 then pays the model load)",
    )
    args = parser.parse_args()

    cfg = get_config()
    from api.search import DEFAULT_TOP_K

    questions = QUESTIONS[: args.limit] if args.limit else QUESTIONS

    warmup = "skipped"
    if not args.no_warmup and not cfg.use_fixtures:
        started = time.perf_counter()
        try:
            llm.chat(
                [{"role": "user", "content": "Reply with the single word: ready"}],
                model=args.model,
            )
            warmup = f"{time.perf_counter() - started:.1f}s"
        except llm.LLMError as exc:
            print(f"Model is not reachable: {exc}", file=sys.stderr)
            print(
                "Start Ollama and pull the configured model, or run in fixture "
                "mode (LIFEVAULT_USE_FIXTURES=true).",
                file=sys.stderr,
            )
            return 1

    documents, chunks = _corpus_counts()
    if documents == 0:
        print(
            "No indexed documents found. Run:\n"
            "  python scripts/generate_demo_corpus.py\n"
            "  python scripts/index_folder.py demo-data/synthetic",
            file=sys.stderr,
        )
        return 1

    results = [run_question(item, args.model) for item in questions]

    meta = {
        "model": args.model or cfg.model_name,
        "embedding_model": cfg.embedding_model_name,
        "use_fixtures": cfg.use_fixtures,
        "top_k": DEFAULT_TOP_K,
        "documents": documents,
        "chunks": chunks,
        "machine": _machine(),
        "warmup_s": warmup,
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    table = render_markdown(results, meta)
    print(table)

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(table.rstrip("\n") + "\n", encoding="utf-8")
        print(f"\n[eval] wrote {args.markdown}", file=sys.stderr)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({"meta": meta, "results": results}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"[eval] wrote {args.json}", file=sys.stderr)

    return 0 if all(result["pass"] for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
