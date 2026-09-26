"""POST /api/chat.

S1 stub: calls llm.chat() (fixture mode by default) directly, with no
retrieval, grounding, or proposal generation. The real flow -- retrieve ->
answer -> verify_grounding -> propose_action -> ... -- is the LangGraph
skeleton in graph/, wired up for real in a later session.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter

import llm
from api.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat_endpoint(req: ChatRequest) -> ChatResponse:
    conversation_id = req.conversation_id or f"conv-{uuid.uuid4().hex[:12]}"
    messages = [{"role": m.role, "content": m.content} for m in req.history]
    messages.append({"role": "user", "content": req.message})

    answer = llm.chat(messages)

    return ChatResponse(
        conversation_id=conversation_id,
        answer=answer,
        citations=[],
        proposal_id=None,
        grounded=False,
    )
