"""POST /api/chat -- question in, grounded cited answer out (S3).

The endpoint runs the compiled LangGraph rather than calling the S3 nodes
directly. That costs a little indirection now and saves a contract change
later: when S7 fills in `propose_action` / `human_approval`, proposals and
the approval interrupt appear here with no edit to this file. Response
shape stays the frozen S1 `ChatResponse` (plus the additive optional S3
fields); no streaming, as specified for S3.

Conversation state: `conversation_id` is the graph thread id, so a
follow-up question resumes the same checkpointed thread. Per-turn working
keys are explicitly reset on the way in -- without that, `answer_retried`
would still be True from the previous turn and silently spend the one
grounding retry this turn is entitled to.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from api.schemas import ChatRequest, ChatResponse, Citation
from config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Compiled graphs are expensive (a SqliteSaver opens its own connection),
# so build one per database path and reuse it. Keyed by path rather than
# cached globally because tests point the config at a fresh temp DB.
_GRAPH_CACHE: Dict[str, Any] = {}
_GRAPH_LOCK = threading.Lock()


def _compiled_graph(database_path: str):
    with _GRAPH_LOCK:
        graph = _GRAPH_CACHE.get(database_path)
        if graph is None:
            from graph.graph import build_graph

            graph = build_graph()
            _GRAPH_CACHE[database_path] = graph
        return graph


def _initial_state(req: ChatRequest, conversation_id: str) -> Dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "user_message": req.message,
        "history": [{"role": m.role, "content": m.content} for m in req.history],
        # Per-turn reset of everything the S3 nodes write.
        "retrieved_chunks": [],
        "answer_text": "",
        "answer_cited_labels": [],
        "answer_cited_chunk_ids": [],
        "answer_retried": False,
        "answer_model": "",
        "confidence": 0.0,
        "grounded": False,
        "citations": [],
        "verification": {},
        "error": None,
    }


def _run_nodes_directly(state: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback path: retrieve -> answer -> verify_grounding, no graph.

    Only used if graph invocation itself fails (a checkpointer problem, for
    instance). A broken graph runtime must not take /api/chat down with it,
    because S3's contract is "answers over HTTP" and the S3 nodes do not
    need the graph to work.
    """
    from graph import nodes

    for node in (nodes.retrieve, nodes.answer, nodes.verify_grounding):
        state.update(node(state))
    return state


def _to_citations(raw: Any) -> List[Citation]:
    citations: List[Citation] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        citations.append(
            Citation(
                document_hash=str(entry.get("document_hash") or ""),
                chunk_id=entry.get("chunk_id"),
                quote=str(entry.get("quote") or ""),
                path=entry.get("path"),
                page=entry.get("page"),
                also_found_at=list(entry.get("also_found_at") or []),
                label=entry.get("label"),
            )
        )
    return citations


def _proposal_id(final_state: Dict[str, Any]) -> Optional[str]:
    """Proposal id, once S7 starts producing proposals. None until then."""
    proposal = final_state.get("proposal")
    if isinstance(proposal, dict):
        identifier = proposal.get("id")
        if identifier is not None:
            return str(identifier)
    return None


@router.post("", response_model=ChatResponse)
def chat_endpoint(req: ChatRequest) -> ChatResponse:
    cfg = get_config()
    conversation_id = req.conversation_id or f"conv-{uuid.uuid4().hex[:12]}"
    state = _initial_state(req, conversation_id)

    started = time.perf_counter()
    try:
        final_state = _compiled_graph(cfg.database_path).invoke(
            state, config={"configurable": {"thread_id": conversation_id}}
        )
    except Exception as exc:  # noqa: BLE001 - documented degradation, see helper
        logger.warning(
            "graph invocation failed (%s); running S3 nodes directly", exc
        )
        final_state = _run_nodes_directly(state)
    latency_ms = int((time.perf_counter() - started) * 1000)

    verification = final_state.get("verification") or {}
    return ChatResponse(
        conversation_id=conversation_id,
        answer=final_state.get("answer_text") or "",
        citations=_to_citations(final_state.get("citations")),
        proposal_id=_proposal_id(final_state),
        grounded=bool(final_state.get("grounded")),
        confidence=float(final_state.get("confidence") or 0.0),
        verification_reason=final_state.get("error") or verification.get("reason"),
        model=final_state.get("answer_model") or None,
        latency_ms=latency_ms,
    )
