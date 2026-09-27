"""Retrieval node (S3).

Thin wrapper: all the ranking logic lives in api/search.py so it can be
tested and driven from scripts/eval.py without building a graph. This
module's only job is turning graph state into a search and back.

Each returned chunk carries at least `content_hash`, `abs_path`, `page` and
`locations`, which is the shape the handover plan pins for downstream
nodes and for the citation payloads the UI renders.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from api.search import DEFAULT_TOP_K, hybrid_search
from graph.state import LifeVaultState


def retrieve_chunks(
    query: str, top_k: int = DEFAULT_TOP_K, db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Hybrid-search `query` and return plain dicts ready for graph state."""
    if not query or not query.strip():
        return []
    return [chunk.to_dict() for chunk in hybrid_search(query, top_k=top_k, db_path=db_path)]


def retrieve(state: LifeVaultState) -> dict:
    """The `retrieve` node: hybrid search over the indexed corpus.

    A retrieval failure is reported on the state's `error` channel rather
    than raised: a question that finds nothing (or hits an index that isn't
    built yet) should still get an honest answer from the answer node, not
    a 500 from /api/chat.
    """
    query = state.get("user_message") or ""
    try:
        chunks = retrieve_chunks(query)
    except Exception as exc:  # noqa: BLE001 - surfaced on the state, not swallowed
        return {
            "retrieved_chunks": [],
            "execution_result": None,
            "error": f"retrieval failed: {exc}",
        }
    return {"retrieved_chunks": chunks, "execution_result": None}
