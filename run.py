#!/usr/bin/env python3
"""LifeVault developer runner.

`python run.py` is the one documented command to bring up the project:
  1. Initialize the SQLite database (idempotent -- safe on every run).
  2. Start the FastAPI backend (uvicorn).
  3. Start the React/Vite UI dev server, if `ui/node_modules` exists.

The worker (worker/worker.py) has no real scan/parse/index loop yet in
S1 -- it's an interface stub -- so there is nothing to start as a
background process for it yet. This is called out explicitly below so
it's obvious that's intentional, not a bug. A later session that gives
Worker real behavior should also give it a real run loop and start it
here as a third subprocess.

A fresh clone must not require any manual edits beyond copying
`.env.example` to `.env` (optional -- defaults work out of the box).
"""
from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def ensure_db() -> None:
    from config import get_config
    from db.init_db import init_db

    cfg = get_config()
    print(f"[run.py] Initializing database at {cfg.database_path} ...")
    init_db(cfg.database_path)


def start_api() -> subprocess.Popen:
    from config import get_config

    cfg = get_config()
    print(f"[run.py] Starting API on http://{cfg.api_host}:{cfg.api_port} ...")
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "api.main:app",
            "--host",
            cfg.api_host,
            "--port",
            str(cfg.api_port),
        ],
        cwd=str(ROOT),
    )


def start_ui() -> Optional[subprocess.Popen]:
    ui_dir = ROOT / "ui"
    if not (ui_dir / "node_modules").exists():
        print(
            "[run.py] ui/node_modules not found -- skipping the UI dev server.\n"
            "         Run `cd ui && npm install` once, then re-run `python run.py`."
        )
        return None
    print("[run.py] Starting UI dev server (npm run dev) ...")
    return subprocess.Popen(["npm", "run", "dev"], cwd=str(ui_dir))


def note_worker_status() -> None:
    print(
        "[run.py] Worker: S1 interface stub only (worker/worker.py) -- no "
        "background scan/parse/index process to start yet."
    )


def main() -> None:
    ensure_db()
    note_worker_status()

    api_proc = start_api()
    ui_proc = start_ui()
    procs = [p for p in (api_proc, ui_proc) if p is not None]

    def shutdown(signum, frame) -> None:  # noqa: ANN001, ARG001
        print("\n[run.py] Shutting down...")
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("\n[run.py] LifeVault is running. Press Ctrl+C to stop.\n")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
