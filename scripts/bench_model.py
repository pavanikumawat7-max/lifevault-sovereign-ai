#!/usr/bin/env python3
"""Check whether the configured local model is available and, if so,
report a real round-trip timing. Never fabricates numbers: if
USE_FIXTURES is on, or the model isn't reachable, it says so and exits
non-zero rather than printing a made-up benchmark.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_config  # noqa: E402
import llm  # noqa: E402


def main() -> int:
    cfg = get_config()
    print(f"Configured chat model:      {cfg.model_name}")
    print(f"Configured embedding model: {cfg.embedding_model_name}")
    print(f"Ollama host:                {cfg.ollama_host}")
    print(f"USE_FIXTURES:                {cfg.use_fixtures}")
    print()

    if cfg.use_fixtures:
        print(
            "Fixture mode is ON: no real model call will be made, so there is "
            "nothing to benchmark. Set LIFEVAULT_USE_FIXTURES=false in .env "
            "and make sure Ollama is running, then re-run this script."
        )
        return 0

    available = llm.is_model_available(cfg.model_name)
    print(f"Model reachable via Ollama: {available}")
    if not available:
        print(
            f"Could not find '{cfg.model_name}' at {cfg.ollama_host}. "
            f"Start Ollama and run `ollama pull {cfg.model_name}`, then re-run."
        )
        return 1

    start = time.perf_counter()
    try:
        reply = llm.chat([{"role": "user", "content": "Reply with the single word: pong"}])
    except llm.LLMUnavailableError as exc:
        print(f"Benchmark chat call failed: {exc}")
        return 1
    elapsed = time.perf_counter() - start

    print(f"Chat round-trip: {elapsed:.3f}s")
    print(f"Response preview: {reply[:120]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
