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

graph/ (LangGraph, 8 nodes -- first three real as of S3)
  retrieve -> answer -> verify_grounding -> propose_action -> policy_check
     -> [human_approval | audit_and_memory] -> [execute | audit_and_memory]
     -> audit_and_memory -> END
  retrieve.py / answer.py / verify.py -- real S3 implementations
  nodes.py -- the node list; re-exports the three above, stubs the rest

api/search.py -- hybrid retrieval: FTS5 BM25 + sqlite-vec, fused with RRF

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
- ~~**Retrieval & answering** (`graph/nodes.py: retrieve`, `answer`,
  `verify_grounding`): real FTS5/vector search, real `llm.chat()` calls,
  real citation/grounding checks.~~ **Done in S3** -- see "S3: hybrid
  retrieval and cited answers" below.

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

---

## S3: hybrid retrieval and cited answers

S3 makes `POST /api/chat` real: a question goes in, and a grounded answer
with citations that name a file path and page comes back. No streaming (out
of scope for S3), and no proposals yet (S7).

### How it works

```
POST /api/chat
  -> graph.retrieve       api/search.py: hybrid_search()
                          FTS5 BM25 top 20  +  sqlite-vec KNN top 20
                          fused with RRF, score = sum(1 / (60 + rank))
                          superseded chunks skipped; duplicate content
                          collapsed by content_hash with other locations
                          attached as "also found at"
  -> graph.answer         numbered chunks C1..Cn, fenced and framed as
                          UNTRUSTED DATA; model returns JSON
                          {answer, cited_chunk_ids, confidence}
  -> graph.verify         every date and quoted phrase in the answer must
                          appear in a chunk the answer cites; on failure,
                          regenerate once, then reply "could not verify"
```

Three details worth knowing:

- **Retrieved document text is untrusted.** It comes from files LifeVault
  did not write, so a document could contain text shaped like an
  instruction. The answer prompt fences every chunk and tells the model
  that fenced content is evidence to quote, never a command to obey.
- **Dates are checked semantically, not just textually.** An answer of
  `2027-06-12` is accepted against a document saying `June 12, 2027`
  (same day, different format), while `June 12, 2028` is rejected.
- **An unverifiable answer is never returned.** It is replaced by the
  literal string `could not verify`, with the reason in
  `verification_reason`.

### Contract changes (additive only)

The frozen S1 shapes are unchanged. S3 adds optional fields with defaults,
so existing clients keep working:

| Model | New optional fields |
|---|---|
| `Citation` | `path`, `page`, `also_found_at`, `label` |
| `ChatResponse` | `confidence`, `verification_reason`, `model`, `latency_ms` |

`path` and `page` were required by the S3 acceptance gate and had no home
in the S1 `Citation`. `LifeVaultState` likewise gained optional keys
(`answer_cited_labels`, `answer_cited_chunk_ids`, `confidence`,
`answer_model`, `answer_retried`, `verification`).

### Running the evaluation

```bash
python scripts/generate_demo_corpus.py          # if not already generated
python scripts/index_folder.py demo-data/synthetic
LIFEVAULT_USE_FIXTURES=false python scripts/eval.py \
    --markdown docs/eval_S3.md --json docs/eval_S3.json
```

10 questions with expected answers and expected source files. Question 10
has no answer in the corpus, so refusing it is its pass condition. The
latest results table is committed at [docs/eval_S3.md](docs/eval_S3.md).

**Result: 9/10 passed, 8/10 grounded, and every one of those 8 grounded
answers cited the expected source file (8/8).** The remaining two are both
refusals: question 10 is *supposed* to be refused, and question 9 is a
genuine miss documented in `docs/handovers/S3.md` -- retrieval puts the
correct chunk at lexical rank 1 and the 3B model declines to answer anyway.

`scripts/eval.py` also runs in fixture mode (no Ollama needed) to check the
plumbing, but the content checks only pass against a real model.

### Model latency and the model choice

Measured on the development laptop -- **MacBook Air M1, 8 GB**, Ollama with
Metal -- over the 10 eval questions, `top_k=4` chunks per answer, warmup
call excluded:

| Model | Size | Per-answer latency (median / max) | Notes |
|---|---|---|---|
| **`llama3.2`** | **3B** | **7.8s / 9.7s** | **Selected.** 9/10 eval, valid JSON every time |
| `phi3` | 3.8B | 50.1s / 60.4s | 3x slower and less reliable JSON (4/5 on a 5-question subset) |
| 7B class | 7B | not measured | Not pulled -- see below |

**Selected model: `llama3.2` (3B)**, which is the `config.py` default.

The handover plan says to fall back to the 3B model if answers take longer
than about 15 seconds. That fallback is already the default here, and 7.8s
median clears the bar. Two honest caveats:

- **Latency varies with machine load.** Early runs on this laptop measured
  a 13-18s median for the same questions. 8 GB is tight with a 2 GB chat
  model plus the embedding model resident, so treat ~8s as the warm
  best case and ~18s as the loaded case.
- **The 7B comparison was not run**, because no 7B model was pulled on this
  machine. The 3.8B measurement above is the evidence for the direction:
  a larger model is dramatically slower here, not marginally. To measure a
  7B yourself:
  ```bash
  ollama pull mistral
  LIFEVAULT_USE_FIXTURES=false python scripts/eval.py --model mistral
  ```

**Warm the model before demoing.** The first call after Ollama starts pays
the model load -- roughly 60s on this laptop, which is long enough to hit
`llm.chat`'s 60s timeout and surface as `could not verify`. One throwaway
call avoids it (`scripts/eval.py` does this automatically):

```bash
ollama run llama3.2 "ready" --keepalive 30m
```

### Setup fixes included in S3

- `.env.example` was referenced by this README and by `run.py`'s docstring
  but was missing from the repository. It is now present and documents
  every variable in `config.py`.

### Known repository-hygiene issue NOT fixed in S3

`.venv/` and `__pycache__/` are tracked even though `.gitignore` already
covers them, and the tracked `.venv` is broken: `.venv/bin/python` points at
system Python 3.9 with no `site-packages`. A fresh clone that follows
`source .venv/bin/activate` therefore gets a non-functional environment --
**create your own virtualenv instead**:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

This was deliberately kept out of the S3 release so the S3 commit contains
feature work only. It is a 64-file change to files P1 owns, and belongs in
its own commit:

```bash
git rm -r --cached .venv
git ls-files | grep __pycache__ | xargs git rm --cached
git commit -m "chore: stop tracking .venv and __pycache__"
```

Flagged for P1, whose Day-5 B1 block is fresh-clone cold start.

---

## S5–S8: watcher, OCR, facts, actions and dashboards

All eight sessions are now implemented — every graph node is real. See
[docs/handovers/S5-S8.md](docs/handovers/S5-S8.md) for the full note,
including the process caveat that these four sessions were done in one
sitting by one person rather than by four people in rotation.

### What was added

| Session | Feature |
|---|---|
| **S5** | `watchdog` filesystem watcher (live indexing) and local OCR via RapidOCR |
| **S6** | Fact extraction: warranty/invoice fields, ISO dates, `/api/facts` filters, facts injected into retrieval |
| **S7** | Proposals, policy gate, human approval with interrupt/resume, two tools, execution, audit + memory |
| **S8** | Approval card, audit viewer with edit diffs, expiry dashboard, memory table |

### New dependencies (all local, no cloud)

```
watchdog>=4.0,<7.0              # S5 watcher
rapidocr-onnxruntime>=1.3,<2.0  # S5 OCR (ONNX models, cached locally)
dateparser>=1.2,<2.0            # S6 date normalization
```

RapidOCR downloads its models once on first use. `worker/ocr.py` degrades to
"no OCR" if it cannot load, so nothing hard-fails without it.

### `run.py` now starts three processes

API + **watcher** + UI. The watcher indexes new files within seconds and can
also be run alone:

```bash
python -m worker.watcher
```

It watches every approved, unpaused root, debounces events, waits for a
file's size to stop changing, skips partial downloads, and never watches the
vault (LifeVault writes `.ics`/`.eml` there — indexing its own output would
loop). A deleted file is flagged `missing`; its document, chunks and facts
are kept so citations degrade gracefully instead of vanishing.

### OCR is a fallback, not the default

A PDF page with 50+ characters of embedded text is never OCR'd — the text
layer is more accurate and far faster. OCR runs on images and on PDF pages
that come back nearly empty. An image yielding almost no text is stored as
metadata only.

### Actions: two tools, both local, neither destructive

```
create_reminder  -> a reminders row + an .ics file in the vault
draft_email      -> an .eml file in the vault, NEVER sent
```

There is no delete tool and no network tool. Every action passes a policy
gate first: a deny-by-default tool allow-list, Pydantic parameter
validation, paths confined to the vault, and **at least one document
citation**. Values that came from document text and look like injected
instructions are flagged so the approval card can highlight them — flagged,
not blocked, because a human decides.

Nothing executes without approval:

```bash
# 1. ask something with an expiry date -> a reminder is proposed
curl -s -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"When does my Dell laptop warranty expire?"}'

# 2. see the queue
curl -s 'http://127.0.0.1:8000/api/approvals?status=pending'

# 3. approve, or edit and approve, or reject
curl -s -X POST http://127.0.0.1:8000/api/approvals/<id> \
  -H 'Content-Type: application/json' \
  -d '{"decision":"edit","parameters":{"due_date":"2027-05-01"}}'

# 4. the chain records all of it
curl -s http://127.0.0.1:8000/api/audit/verify
```

**Approval survives an API restart.** The graph is compiled with
`interrupt_before=["human_approval"]` and checkpointed to SQLite, and the
proposal row stores its `thread_id` — so a decision can arrive in a process
that knows nothing about the paused turn. (Static interrupts rather than
LangGraph's dynamic `interrupt()`, because `langgraph` is pinned `<0.3`.)

### Extracting facts

Facts are extracted automatically while indexing. To (re-)run over
everything already indexed:

```bash
python -c "from worker.facts import extract_all; print(extract_all())"
```

Dates are stored twice: `value` keeps the document's own wording so citations
read naturally, `norm_value` keeps ISO-8601 so `?expiring_within=60` is pure
SQL. **Every fact must quote its source**, and a fact whose quote is not
literally in its chunk is discarded. Correcting a value through
`PATCH /api/facts/{id}` sets `user_corrected`, which protects it from being
overwritten by future re-indexing.

### Current validation

| Check | Result |
|---|---|
| `pytest -q` | **113 passed** |
| `python scripts/smoke.py` | **24/24** |
| `cd ui && npm test` | 15 passed |
| `scripts/eval.py` (llama3.2 3B) | **9/10**, 10/10 grounded, ~15 s median |
| New file → searchable | ~4 s |
| Audit hash chain | verifies |

Latency rose from ~8 s (S3) to ~15 s because the prompt now also carries the
extracted-facts block. That buys correct answers on "which warranty has
already expired", which previously failed.

### Two known issues that affect a demo

1. **The demo script's phrasing still refuses.** *"My Dell screen is
   flickering. Am I still covered?"* returns `could not verify` — the 3B
   model will not infer that a flickering screen falls under a hardware
   warranty, though it cites the right documents. Use **"Is my Dell XPS 15
   still under warranty?"** or **"When does my Dell laptop warranty
   expire?"**, both of which answer correctly.
2. **`ui/node_modules` is committed and is a Windows build**, so the UI will
   not start on macOS or Linux until you `rm -rf ui/node_modules && npm
   install`. It should be untracked — see the handover note.
