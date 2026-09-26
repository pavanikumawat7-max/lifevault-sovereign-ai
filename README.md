# LifeVault

**Team Lumina -- ASYNC 2026 Track 1: Sovereign AI**

LifeVault is a local-first personal document assistant: it watches folders
you grant it access to, understands the documents in them, answers
questions grounded in your own files, and -- eventually -- proposes
actions (with your explicit approval) on your behalf. Everything runs on
your machine. No cloud calls, no API keys, no data leaving your computer.

This is the **S1 foundation**: repository structure, database schema, a
frozen set of typed API contracts, stub implementations of every
component, and one piece of real logic -- an append-only, hash-chained
audit log. Everything else is intentionally a clean, typed stub for later
sessions to build on top of without changing the contracts below.

---

## Architecture overview

```
run.py --------------------------------------------------------------+
  |                                                                  |
  v                                                                  v
api/ (FastAPI)                                                  ui/ (React + Vite)
  main.py -- app assembly, CORS, DB init on startup                Consent / Chat / Approvals / Audit / Expiry
  schemas.py -- frozen Pydantic request/response contracts         pages, an API client, fixture-backed
  audit.py -- REAL hash-chained append-only audit log
  routes/ -- one typed stub route module per resource
       (roots, index, chat, documents, facts, approvals, memory, audit)

graph/ (LangGraph skeleton, 8 nodes)
  retrieve -> answer -> verify_grounding -> propose_action -> policy_check
     -> [human_approval | audit_and_memory] -> [execute | audit_and_memory]
     -> audit_and_memory -> END

worker/    -- scan() / parse() / index() interface (stub)
tools/     -- tool registry interface (stub, no tools registered)
policy/    -- deny-by-default policy allow-list (stub, no rules configured)
llm.py     -- local Ollama wrapper (chat / embed / structured_output),
              with a fixture mode that needs no model installed

db/
  schema.sql  -- all 8 tables, FTS5 full-text index + triggers, indexes
  connect.py  -- the one place that opens a SQLite connection (WAL, FKs, busy timeout)
  init_db.py  -- applies schema.sql; also creates the sqlite-vec table if
                 that extension is available, sized from config

config.py -- single source of truth for all configuration (env-driven)
```

The **only real feature logic in S1 is the audit log** (`api/audit.py`).
Everything else -- routes, the graph nodes, the worker, tools, policy, the
UI -- returns/consumes fixture data on purpose. See "What S2 is expected
to implement" below.

---

## Prerequisites

- Python 3.10+ (developed against 3.12)
- Node.js 18+ and npm (for the UI; the API and tests work without it)
- [Ollama](https://ollama.com) (optional -- only needed once you turn off
  fixture mode; everything runs without it by default)

## Python setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Frontend setup

```bash
cd ui
npm install
cd ..
```

If you skip this step, `python run.py` still starts the API -- it just
prints a note and skips launching the UI dev server.

## Environment setup

```bash
cp .env.example .env
```

Every variable in `.env.example` has a working default in `config.py`, so
this step is optional -- LifeVault runs with no `.env` file at all, in
fixture mode, out of the box.

## How to initialize the database

Happens automatically on `python run.py` / on API startup / when
`scripts/smoke.py` runs. To do it explicitly:

```bash
python -m db.init_db
```

Safe to re-run -- every statement in `schema.sql` is `IF NOT EXISTS`.

## How to run

```bash
python run.py
```

This is the one documented primary command. It will:
1. Initialize the SQLite database if needed.
2. Start the FastAPI backend at `http://127.0.0.1:8000`.
3. Start the Vite UI dev server at `http://localhost:5173` (if `ui/node_modules` exists).

Press `Ctrl+C` to stop everything it started.

To run the API alone:

```bash
uvicorn api.main:app --reload
```

To run the UI alone:

```bash
cd ui && npm run dev
```

## How to run smoke tests

```bash
python scripts/smoke.py
```

Exercises every required endpoint via an in-process `TestClient` (no port
needed) and fails clearly and loudly on a missing route, wrong status
code, or unparseable JSON body.

## How to run pytest

```bash
pytest -q
```

Covers: config, DB init/schema/WAL/foreign keys/FTS5, the real audit hash
chain (including tamper detection), LLM fixture mode, worker/tool/policy
interfaces, the frozen Pydantic schemas, every API route, and the
LangGraph skeleton's node-to-node execution and routing rules.

Tests that need `fastapi`/`pydantic` or `langgraph` use
`pytest.importorskip`, so `pytest -q` degrades gracefully (skips instead
of erroring) on a partial install, but a full
`pip install -r requirements.txt` is expected to make every test run and
pass.

## How to use fixture mode

`LIFEVAULT_USE_FIXTURES=true` is the default. In this mode:
- `llm.chat()` returns a canned string, no network call.
- `llm.embed()` returns a zero-vector of the configured
  `LIFEVAULT_EMBEDDING_DIM`, no network call.
- Every API route returns fixture data from `api/fixtures.py`
  (except `/api/audit*`, which is real and backed by the actual
  database).

This is what lets `run.py`, `scripts/smoke.py`, and `pytest -q` all pass
on a machine with no GPU and no Ollama installed.

## How to configure Ollama

1. Install Ollama: https://ollama.com
2. Pull the configured models:
   ```bash
   ollama pull llama3.2
   ollama pull nomic-embed-text
   ```
3. Set `LIFEVAULT_USE_FIXTURES=false` in `.env`.
4. Check it's working:
   ```bash
   python scripts/bench_model.py
   ```
   This checks whether the configured model is reachable and reports a
   real chat round-trip time. It never fabricates a number -- if fixture
   mode is on, or the model isn't reachable, it says so and exits
   non-zero instead of printing anything made up.

---

## Repository structure

```
LifeVault/
  api/
    main.py, schemas.py, audit.py, deps.py, fixtures.py
    routes/roots.py, index.py, chat.py, documents.py, facts.py,
           approvals.py, memory.py, audit.py
  db/
    schema.sql, connect.py, init_db.py
  graph/
    state.py, nodes.py, graph.py
  tools/
    registry.py
  policy/
    policy.py
  worker/
    worker.py
  ui/
    src/pages/{Consent,Chat,Approvals,Audit,Expiry}.jsx
    src/api/client.js
  demo-data/     -- reserved for later sessions' sample documents
  docs/handovers/TEMPLATE.md
  handovers/     -- actual handover write-ups land here (see S1.md)
  scripts/
    smoke.py, bench_model.py
  tests/
    conftest.py + one test module per S1 component
  config.py, llm.py, run.py, requirements.txt, .env.example, .gitignore
```

---

## Frozen S1 API contracts

All models below live in `api/schemas.py`. **Frozen as of S1**: later
sessions may add new *optional* fields with defaults, but must not rename,
remove, or change the type of an existing field.

| Method | Path                              | Request model            | Response model             |
|--------|------------------------------------|---------------------------|------------------------------|
| GET    | `/api/roots`                      | --                          | `ListRootsResponse`         |
| POST   | `/api/roots`                      | `CreateRootRequest`         | `CreateRootResponse`        |
| DELETE | `/api/roots/{id}`                 | --                          | `DeleteRootResponse`        |
| POST   | `/api/index/pause`                | --                          | `PauseIndexResponse`        |
| POST   | `/api/index/resume`               | --                          | `ResumeIndexResponse`       |
| GET    | `/api/index/status`               | --                          | `GetIndexStatusResponse`    |
| POST   | `/api/chat`                       | `ChatRequest`               | `ChatResponse`               |
| GET    | `/api/documents/{hash}`           | --                          | `DocumentDetailResponse`    |
| GET    | `/api/documents/{hash}/preview`   | --                          | `DocumentPreviewResponse`   |
| POST   | `/api/documents/{hash}/open`      | `OpenDocumentRequest`       | `OpenDocumentResponse`      |
| POST   | `/api/documents/{hash}/reveal`    | --                          | `RevealDocumentResponse`    |
| GET    | `/api/facts`                      | --                          | `ListFactsResponse`         |
| PATCH  | `/api/facts/{id}`                 | `UpdateFactRequest`         | `UpdateFactResponse`        |
| POST   | `/api/approvals/{proposal_id}`    | `ApprovalDecisionRequest`   | `ApprovalDecisionResponse`  |
| GET    | `/api/memory`                     | --                          | `MemoryResponse`             |
| GET    | `/api/audit`                      | --                          | `AuditListResponse` (real)  |
| GET    | `/api/audit/verify`               | --                          | `AuditVerifyResponse` (real)|

Plus `GET /api/health` (not part of the frozen resource contracts, just a
liveness check).

## What S2 is expected to implement

S1 deliberately leaves all of the following as typed stubs/interfaces.
**None of the frozen contracts above should need to change** to build
these:

- **Worker** (`worker/worker.py`): real `scan()` (filesystem watching +
  content-hash dedup, writing to `index_roots`/`documents`/`file_locations`),
  `parse()` (PDF/DOCX text extraction + chunking into `chunks`), and
  `index()` (populating `chunks_fts` and `chunks_vec`).
- **Retrieval & answering** (`graph/nodes.py: retrieve`, `answer`,
  `verify_grounding`): real FTS5/vector search, real `llm.chat()` calls,
  real citation/grounding checks.

## S2 ingestion usage

Generate the synthetic corpus, then approve and index any folder:

```bash
python scripts/generate_demo_corpus.py
python scripts/index_folder.py demo-data/synthetic
```

The CLI prints found, unique, duplicate, skipped, processed, chunk, and
vector-availability counts. It writes documents, locations, page-aware
chunks, FTS5 rows, and—when `sqlite-vec` is available—`chunks_vec` rows to
the configured `LIFEVAULT_DB_PATH`.
- **Proposals & policy** (`graph/nodes.py: propose_action`, `policy_check`;
  `tools/registry.py`; `policy/policy.py`): real tool registrations, real
  `PolicyRule`s, real proposal generation written to the `proposals` table.
- **Human approval** (`graph/nodes.py: human_approval`): replace the
  placeholder with a real LangGraph interrupt that pauses the graph until
  `POST /api/approvals/{proposal_id}` resumes it with the human's decision.
- **Execution & memory** (`graph/nodes.py: execute`, `audit_and_memory`):
  actually invoke the approved tool, and write real rows to `audit_log`
  (via `api.audit.AuditLog.log(...)`, already real and tested) and `memory`.
- **Real UI behavior**: wire the existing 5 pages to the real endpoints
  once they return real data instead of fixtures.

Use `docs/handovers/TEMPLATE.md` for every handover; `handovers/S1.md` is
the completed one for this session.
