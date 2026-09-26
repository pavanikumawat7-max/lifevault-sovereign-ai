"""Local LLM wrapper.

Intended stack: Ollama running `llama3.2` for chat and a local embedding
model (default `nomic-embed-text`) -- both configured, never hard-coded,
via config.py. No API keys, no cloud calls: everything talks to
`ollama_host` (default http://localhost:11434).

Fixture mode (`USE_FIXTURES=true`, the default) makes every function
return deterministic canned output with no network call at all, so the
rest of S1 -- routes, the graph skeleton, tests -- runs on a machine with
no GPU and no Ollama installed. Flip `USE_FIXTURES=false` once Ollama is
running locally with the configured models pulled.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import requests

from config import get_config


class LLMError(Exception):
    """Base class for LLM wrapper errors."""


class LLMUnavailableError(LLMError):
    """Raised when the local model server can't be reached or errors out."""


FIXTURE_CHAT_REPLY = (
    "[fixture] This is a canned LifeVault response. Set USE_FIXTURES=false "
    "and run Ollama locally to get real answers."
)


def _base_url() -> str:
    return get_config().ollama_host.rstrip("/")


def is_model_available(model_name: Optional[str] = None) -> bool:
    """Best-effort check that `model_name` is pulled and Ollama is up.

    Never raises -- returns False on any connectivity/parsing problem so
    callers (e.g. scripts/bench_model.py) can report cleanly instead of
    crashing.
    """
    cfg = get_config()
    model_name = model_name or cfg.model_name
    try:
        resp = requests.get(f"{_base_url()}/api/tags", timeout=3)
        resp.raise_for_status()
        models = resp.json().get("models", [])
        return any(str(m.get("name", "")).startswith(model_name) for m in models)
    except Exception:
        return False


def chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.2,
) -> str:
    """Chat completion. `messages` is a list of {"role", "content"} dicts.

    In fixture mode, returns FIXTURE_CHAT_REPLY without touching the
    network. Otherwise calls Ollama's /api/chat and raises
    LLMUnavailableError (never a raw requests exception) on failure.
    """
    cfg = get_config()
    if cfg.use_fixtures:
        return FIXTURE_CHAT_REPLY

    model = model or cfg.model_name
    try:
        resp = requests.post(
            f"{_base_url()}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature},
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "")
    except requests.RequestException as exc:
        raise LLMUnavailableError(
            f"Could not reach local Ollama chat model '{model}' at "
            f"{_base_url()}: {exc}"
        ) from exc


def embed(text: str, model: Optional[str] = None) -> List[float]:
    """Embed `text`. Vector length always equals config.embedding_dimension.

    In fixture mode returns a zero vector of the configured dimension (so
    downstream code that checks `len(vector) == embedding_dimension`
    exercises the real contract even without a model). Real mode calls
    Ollama's /api/embeddings and returns whatever the model produces --
    callers that need to enforce dimension match should do so themselves,
    since a misconfigured embedding_dimension vs. actual model output is
    exactly the kind of thing S1 wants surfaced, not silently patched.
    """
    cfg = get_config()
    if cfg.use_fixtures:
        return [0.0] * cfg.embedding_dimension

    model = model or cfg.embedding_model_name
    try:
        resp = requests.post(
            f"{_base_url()}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("embedding", [])
    except requests.RequestException as exc:
        raise LLMUnavailableError(
            f"Could not reach local Ollama embedding model '{model}' at "
            f"{_base_url()}: {exc}"
        ) from exc


def structured_output(
    prompt: str, schema_hint: str, model: Optional[str] = None
) -> Dict[str, Any]:
    """Ask the model for JSON matching `schema_hint` (a human-readable
    description, not a formal schema -- S1 keeps this simple).

    Fixture mode returns a small stub dict instead of calling chat(), so
    it never depends on the model actually following instructions.
    """
    cfg = get_config()
    if cfg.use_fixtures:
        return {"stub": True, "prompt_preview": prompt[:80]}

    raw = chat(
        [
            {
                "role": "system",
                "content": f"Respond ONLY with JSON matching: {schema_hint}",
            },
            {"role": "user", "content": prompt},
        ],
        model=model,
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model did not return valid JSON: {exc}") from exc
