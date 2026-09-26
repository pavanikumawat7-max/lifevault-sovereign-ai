"""FastAPI application entry point.

`app` is what `run.py` and uvicorn serve, and what scripts/smoke.py drives
via fastapi.testclient.TestClient. All route modules are frozen-contract
stubs except api/routes/audit.py, which is backed by the real hash-chained
audit log in api/audit.py.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_config
from db.init_db import init_db
from api.routes import (
    approvals,
    audit as audit_routes,
    chat,
    documents,
    facts,
    index,
    memory,
    roots,
)


def create_app() -> FastAPI:
    cfg = get_config()
    app = FastAPI(
        title="LifeVault API",
        description="Sovereign, local-first personal document assistant.",
        version="0.1.0-s1",
    )

    origins = [o.strip() for o in cfg.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(roots.router)
    app.include_router(index.router)
    app.include_router(chat.router)
    app.include_router(documents.router)
    app.include_router(facts.router)
    app.include_router(approvals.router)
    app.include_router(memory.router)
    app.include_router(audit_routes.router)

    @app.get("/api/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok", "service": "lifevault-api", "version": app.version}

    @app.on_event("startup")
    def on_startup() -> None:
        # Guarantees a fresh clone works with zero manual steps: the DB
        # (and audit_log table the audit routes depend on) always exists
        # by the time the first request arrives.
        init_db(cfg.database_path)

    return app


app = create_app()
