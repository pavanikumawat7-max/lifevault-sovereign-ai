# LifeVault

**Team Lumina | ASYNC 2026 Track 1: Sovereign AI**

LifeVault is a local-first personal document assistant. You grant it access
to specific folders, it indexes the PDFs inside them, and you ask questions
in plain language. Every answer comes with citations that name the file and
page it came from, and an answer that cannot be backed by your documents is
refused instead of guessed.

Everything runs on your machine. There are no cloud calls, no API keys, and
no data leaves your computer. The language and embedding models run locally
through [Ollama](https://ollama.com).

---

## Status

| Area | State | Notes |
|---|---|---|
| Folder consent (grant / revoke / pause) | **Real** | Revoking a folder removes only data no other approved folder still references |
| Ingestion (scan, parse, chunk, embed, index) | **Real** | PDFs and images, page-aware; local OCR fallback (S5) |
| Filesystem watcher (live indexing) | **Real** | New file searchable in about 4 s (S5) |
| Hybrid retrieval (FTS5 + sqlite-vec, RRF) | **Real** | `api/search.py` |
| Cited answers with grounding checks | **Real** | `POST /api/chat`, no streaming |
| Document preview, open, reveal | **Real** | `open` / `reveal` not yet verified on a real desktop |
| Chat UI, citation chips, citation viewer | **Real** | |
| Index status UI with pause / resume / "Index now" | **Real** | Polls every 4 seconds |
| Hash-chained audit log and `/api/audit*` | **Real** | Chat turns, proposals, decisions and executions are all logged (S7) |
| Fact extraction (`/api/facts`, Expiry page) | **Real** | Warranty/invoice/expiry facts, each with a verified source quote (S6) |
| Action proposals, policy, tools, human approval, execution | **Real** | Two local tools; nothing runs without approval; survives restart (S7) |
| Memory (`/api/memory`) | **Real** | Remembers last decisions as defaults, never as permissions (S7) |

All eight graph nodes are now implemented. See [S5–S8](#s5s8-watcher-ocr-facts-actions-and-dashboards)
below and [docs/handovers/S5-S8.md](docs/handovers/S5-S8.md). The API
contracts are frozen; later sessions only add optional fields.

---

## Quickstart

### Prerequisites

- Python 3.10+ (developed against 3.12)
- Node.js 18+ and npm (for the UI; the API and tests work without it)
- [Ollama](https://ollama.com) (optional: only needed once fixture mode is off)

### 1. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Frontend dependencies

```bash
cd ui
npm install
cd ..
```

If you skip this, `python run.py` still starts the API; it prints a note and
skips the UI dev server.

### 3. Configuration (optional)

```bash
cp .env.example .env
```

Every variable has a working default in `config.py`, so this step is
optional. With no `.env` at all, LifeVault starts in **fixture mode**
(see below) and runs fully offline.

### 4. Run

```bash
python run.py
```

This initializes the SQLite database if needed, starts the FastAPI backend
at `http://127.0.0.1:8000`, and starts the Vite UI at
`http://localhost:5173` when `ui/node_modules` exists. Press `Ctrl+C` to stop
everything it started.

Run the pieces separately if you prefer:

```bash
uvicorn api.main:app --reload      # API only
cd ui && npm run dev               # UI only (proxies /api to :8000)
```

### 5. Try it with the demo corpus

```bash
python scripts/generate_demo_corpus.py          # only if demo-data/synthetic is missing
python scripts/index_folder.py demo-data/synthetic
```

Or do it from the UI: open **Consent & Roots**, add the
`demo-data/synthetic` folder, and click **Index now**.

Then open **Chat** and ask a question such as *"When does my Dell laptop
warranty expire?"* Click a citation chip to open the citation viewer, which
shows the quoted text, the file path, the page, and any other locations
holding an identical copy.

---

## Fixture mode vs. real models

`LIFEVAULT_USE_FIXTURES=true` is the default, so a fresh clone runs with no
GPU and no Ollama. In fixture mode:

- `llm.chat()` returns a canned string and `llm.embed()` returns a zero vector
  of the configured width. No network calls are made.
- Only the keyword (BM25) side of retrieval carries signal, because every
  stored vector is equidistant.
- Fixture answers do not reflect your documents, so content checks only mean
  something against a real model.

To use real local models:

```bash
ollama pull llama3.2               # chat model, 3B
ollama pull nomic-embed-text       # embeddings, 768 dimensions
```

Then set `LIFEVAULT_USE_FIXTURES=false` in `.env`, re-index any folders you
indexed in fixture mode (so they get real embeddings), and check the setup:

```bash
python scripts/bench_model.py
```

`bench_model.py` reports a real chat round-trip time. It never prints a made-up
number: if fixture mode is on or the model is unreachable, it says so and
exits non-zero.

**Warm the model before a demo.** The first call after Ollama starts pays the
model load, roughly 60 seconds on the development laptop. That is long enough
to hit `llm.chat`'s 60-second timeout, which then surfaces as
`could not verify`. One throwaway call avoids it:

```bash
ollama run llama3.2 "ready" --keepalive 30m
```

---

## Configuration

All settings are environment variables read by `config.py`, which is the
single source of truth. `.env.example` documents each one.

| Variable | Default | Purpose |
|---|---|---|
| `LIFEVAULT_DB_PATH` | `data/lifevault.db` | SQLite database (created automatically) |
| `LIFEVAULT_VAULT_DIR` | `vault` | Where action tools write `.ics` reminders and `.eml` drafts; the only writable location |
| `LIFEVAULT_DEMO_DATA_DIR` | `demo-data` | Sample documents |
| `LIFEVAULT_MODEL_NAME` | `llama3.2` | Ollama chat model |
| `LIFEVAULT_EMBEDDING_MODEL_NAME` | `nomic-embed-text` | Ollama embedding model |
| `LIFEVAULT_EMBEDDING_DIM` | `768` | Vector width; must match the embedding model. Changing it requires a re-index |
| `LIFEVAULT_OLLAMA_HOST` | `http://localhost:11434` | Ollama server |
| `LIFEVAULT_MAX_UPLOAD_SIZE_MB` | `50` | Files larger than this are skipped during ingestion |
| `LIFEVAULT_MAX_CHUNK_CHARS` | `2000` | Defined in `config.py` but not currently read; chunking is token-based (about 500 tokens) |
| `LIFEVAULT_USE_FIXTURES` | `true` | `true` = no model calls; `false` = real Ollama |
| `LIFEVAULT_API_HOST` / `LIFEVAULT_API_PORT` | `127.0.0.1` / `8000` | API bind address |
| `LIFEVAULT_UI_DEV_PORT` | `5173` | Vite dev server port |
| `LIFEVAULT_CORS_ORIGINS` | `http://localhost:5173` | Allowed origins, comma-separated |
| `LIFEVAULT_LOG_LEVEL` | `INFO` | Logging level |

If you change the API or UI ports, also update the proxy in
`ui/vite.config.js`, which currently targets `http://127.0.0.1:8000`.

---

## The UI

| Page | What it does |
|---|---|
| **Chat** | Ask questions. Answers show citation chips (`label: filename p.N`) and an "unverified" badge, with the reason as a tooltip, when grounding failed |
| **Consent & Roots** | Grant or revoke folders, start indexing for a folder, and pause or resume indexing globally |
| **Index Status** | Live state (idle, scanning, indexing, paused, error), folder counts, documents and chunks indexed, last run time |
| **Approvals** | Pending action proposals: editable parameters, evidence, tier badge, untrusted-value highlighting; Approve / Edit & approve / Reject; memory table |
| **Audit Log** | Hash-chained entries that expand to show proposal, edit diff, policy verdict and tool output; **Verify chain** |
| **Expiry & Facts** | Expiring-within 30/60/90/365 days with expired/active badges; every fact with its source quote, editable inline |

The **citation viewer** (opened from any citation chip) previews the cited
chunk, lists "also found at" duplicates, and offers **Open original** and
**Reveal in file manager**.

---

## How it works

```
run.py ----------------------------------------------------------+
  |                                                              |
  v                                                              v
api/ (FastAPI)                                         ui/ (React + Vite)
  main.py      app assembly, CORS, DB init on startup     Chat, Consent, Index Status,
  schemas.py   frozen Pydantic request/response models    Approvals, Audit, Expiry,
  audit.py     hash-chained append-only audit log         citation viewer
  search.py    hybrid retrieval (FTS5 + sqlite-vec + RRF)
  routes/      one module per resource

graph/ (LangGraph, 8 nodes; all real)
  retrieve -> answer -> verify_grounding -> propose_action -> policy_check
    -> [human_approval | audit_and_memory] -> [execute | audit_and_memory]
    -> audit_and_memory -> END

worker/    scan -> parse -> chunk -> embed -> index
api/tools/ create_reminder (.ics) and draft_email (.eml, never sent)
policy/    deny-by-default allow-list, validation, vault containment, citation rule
llm.py     local Ollama wrapper: chat / embed / structured_output, with fixture mode
db/        schema.sql, connection helper (WAL, foreign keys), init
config.py  single source of truth for configuration
```

### Ingestion (`worker/`)

Indexing only reads your files; it never modifies them. For each approved
folder the worker:

1. **Scans** with read-only `os.scandir()`. It skips hidden and runtime
   files, videos, executables, incomplete downloads, unsupported formats,
   anything matching the folder's exclude globs, and files over the size limit.
2. **Deduplicates** by content. A cheap path/size/mtime check avoids
   re-hashing unchanged files; otherwise a streaming SHA-256 identifies the
   document. The same content in two places is one document with two
   locations.
3. **Parses** PDFs page by page with PyMuPDF; images and near-empty PDF pages go through local OCR (RapidOCR).
4. **Chunks** into roughly 500-token pieces with a 60-token overlap, keeping
   page number, ordinal, and source position.
5. **Embeds** through `llm.embed` in batches of 32.
6. **Indexes** chunks, FTS5 rows, and (when `sqlite-vec` is available) vectors
   in a single transaction.

FTS5 and everything else keep working if the `sqlite-vec` extension cannot
load on a given machine; only vector search is lost.

### Question answering (`POST /api/chat`)

```
question
  -> retrieve   FTS5 BM25 top 20 + sqlite-vec KNN top 20, fused with
                Reciprocal Rank Fusion: score = sum(1 / (60 + rank)).
                Superseded chunks are skipped. Identical content is
                collapsed by content hash, with other locations attached
                as "also found at". The top 4 chunks go to the model.
  -> answer     Chunks are numbered C1..Cn, fenced, and framed as
                UNTRUSTED DATA. The model returns JSON:
                {answer, cited_chunk_ids, confidence}. Temperature is 0.
  -> verify     Every date and every quoted phrase in the answer must
                appear in a chunk the answer cites. On failure the answer
                is regenerated once with the reason fed back; if it fails
                again the reply is the literal string "could not verify".
```

Three properties worth knowing:

- **Retrieved text is untrusted.** Documents are files LifeVault did not
  write, so one could contain text shaped like an instruction. The prompt
  tells the model that fenced content is evidence to quote, never a command.
- **Dates are compared semantically.** `2027-06-12` is accepted against a
  document saying `June 12, 2027` (same day, different format), while
  `June 12, 2028` is rejected.
- **An unverifiable answer is never returned.** It is replaced by
  `could not verify`, with the reason in `verification_reason`. Citations the
  model invents (a label it was never shown) are dropped and counted as a
  grounding failure.

### Audit log (`api/audit.py`)

Each row commits to its event, canonicalized payload, timestamp, and the
previous row's hash. Editing, reordering, or splicing any historical row
breaks the chain from that point on, and `GET /api/audit/verify` reports the
first offending row. The module uses only the standard library.

The log and its endpoints are real and tested, and `audit_and_memory` writes
every chat turn, proposal, decision and execution to it.

---

## API

All models live in `api/schemas.py`. Contracts are **frozen**: later sessions
may add new optional fields with defaults, but must not rename, remove, or
retype an existing field.

| Method | Path | Request | Response | State |
|---|---|---|---|---|
| GET | `/api/roots` | | `ListRootsResponse` | Real |
| POST | `/api/roots` | `CreateRootRequest` | `CreateRootResponse` | Real |
| DELETE | `/api/roots/{id}` | | `DeleteRootResponse` | Real |
| POST | `/api/index/start` | `StartIndexRequest` | `StartIndexResponse` | Real |
| POST | `/api/index/pause` | | `PauseIndexResponse` | Real |
| POST | `/api/index/resume` | | `ResumeIndexResponse` | Real |
| GET | `/api/index/status` | | `GetIndexStatusResponse` | Real |
| POST | `/api/chat` | `ChatRequest` | `ChatResponse` | Real |
| GET | `/api/documents/{hash}` | | `DocumentDetailResponse` | Real |
| GET | `/api/documents/{hash}/preview` | | `DocumentPreviewResponse` | Real |
| POST | `/api/documents/{hash}/open` | `OpenDocumentRequest` | `OpenDocumentResponse` | Real |
| POST | `/api/documents/{hash}/reveal` | | `RevealDocumentResponse` | Real |
| GET | `/api/facts` | | `ListFactsResponse` | Real |
| PATCH | `/api/facts/{id}` | `UpdateFactRequest` | `UpdateFactResponse` | Real |
| POST | `/api/approvals/{proposal_id}` | `ApprovalDecisionRequest` | `ApprovalDecisionResponse` | Real |
| GET | `/api/memory` | | `MemoryResponse` | Real |
| GET | `/api/audit` | | `AuditListResponse` | Real |
| GET | `/api/audit/verify` | | `AuditVerifyResponse` | Real |
| GET | `/api/health` | | liveness check | Real |

Notes:

- `/api/index/start` runs ingestion in a background thread and returns
  immediately; poll `/api/index/status` for progress. Only one ingest run
  can be active at a time.
- `/api/documents/{hash}*` return 404 for a hash that is not indexed.
  `open` and `reveal` shell out to the platform opener (`open`, `xdg-open`, or
  `explorer`) and report `opened: false` with a message on any failure rather
  than raising.
- Interactive docs are available at `http://127.0.0.1:8000/docs` while the API
  is running.

## Testing

```bash
pytest -q                          # backend suite
python scripts/smoke.py            # in-process check of every endpoint
cd ui && npm test                  # UI unit tests (citation helpers and chips)
cd ui && npm run build             # production build check
```

- `pytest -q` covers config, DB init/schema/WAL/foreign keys/FTS5, the audit
  hash chain (including tamper detection), LLM fixture mode, ingestion,
  hybrid retrieval, grounding verification, the frozen schemas, every API
  route, and the graph's routing rules. Tests that need `fastapi`, `pydantic`,
  or `langgraph` use `pytest.importorskip`, so a partial install skips rather
  than errors. A full `pip install -r requirements.txt` runs everything.
- `scripts/smoke.py` uses an in-process `TestClient` (no port needed) and
  fails loudly on a missing route, wrong status code, or unparseable body.
- The UI has not been click-tested in a browser in CI. Before a live demo,
  open `http://localhost:5173` once and click through **Consent -> Index
  Status -> Chat -> a citation chip -> Open / Reveal**.

### Answer-quality evaluation

```bash
python scripts/generate_demo_corpus.py          # if not already generated
python scripts/index_folder.py demo-data/synthetic
LIFEVAULT_USE_FIXTURES=false python scripts/eval.py \
    --markdown docs/eval_S3.md --json docs/eval_S3.json
```

The eval runs 10 questions with expected answers and expected source files.
Question 10 has no answer in the corpus, so refusing it is its pass
condition. The full table is committed at [docs/eval_S3.md](docs/eval_S3.md).

**Result (S3, `llama3.2`): 9 of 10 passed and 8 of 10 grounded. Every
grounded answer cited the expected source file.** The two ungrounded results
are both refusals: question 10 is supposed to be refused, and question 9 is a
genuine miss (retrieval ranks the right chunk first, but the 3B model declines
to answer). `scripts/eval.py` also runs in fixture mode to exercise the
plumbing, but content checks only pass against a real model.

### Model choice and latency

Measured at S3 on a MacBook Air M1 with 8 GB, using Ollama with Metal, over
the 10 eval questions with 4 chunks per answer and the warmup call excluded:

| Model | Size | Latency (median / max) | Notes |
|---|---|---|---|
| **`llama3.2`** | **3B** | **7.8s / 9.7s** | **Selected default.** 9/10 on the eval, valid JSON every time |
| `phi3` | 3.8B | 50.1s / 60.4s | About 6x slower, and less reliable JSON (4/5 on a 5-question subset) |
| 7B class | 7B | not measured | No 7B model was pulled |

Treat about 8s as the warm best case. On an 8 GB machine, latency rose to
13 to 18s under load, since the chat and embedding models are both resident.
To compare a 7B model yourself:

```bash
ollama pull mistral
LIFEVAULT_USE_FIXTURES=false python scripts/eval.py --model mistral
```

---

## Repository structure

```
api/          main.py, schemas.py, audit.py, search.py, deps.py, fixtures.py
  routes/     roots, index, chat, documents, facts, approvals, memory, audit
db/           schema.sql, connect.py, init_db.py
graph/        state.py, graph.py, nodes.py, retrieve.py, answer.py, verify.py
worker/       worker.py, scanner.py, parse.py, chunk.py, index.py
tools/        registry.py
policy/       policy.py
ui/
  src/        App.jsx, pages/, components/, api/client.js, utils/
  tests/      citation helper and chip tests
scripts/      smoke.py, bench_model.py, eval.py, index_folder.py,
              generate_demo_corpus.py
tests/        one module per component, plus S2 ingestion and S3 retrieval
demo-data/    synthetic corpus (PDFs, DOCX, one screenshot)
docs/         eval_S3.md/.json, handovers/
data/         SQLite database lives here (git-ignored)
vault/        action-tool output (.ics / .eml), git-ignored
config.py, llm.py, run.py, requirements.txt, .env.example, pytest.ini
```

### Demo corpus

`demo-data/synthetic` holds 110 files: 104 PDFs (100 filler records, a Dell
invoice, a Dell warranty, an exact duplicate of that warranty in `folder_B`,
and an expired refrigerator warranty), plus 5 DOCX notes and 1 screenshot.
Indexing it yields 103 unique documents (one duplicate) and 104 chunks. DOCX
files are skipped; the screenshot is indexed via OCR. All content is synthetic.
`scripts/generate_demo_personal_docs.py` builds the personal-documents demo set
used in [docs/demo_script.md](docs/demo_script.md).

---

## Known limitations

- **PDFs and images only.** DOCX is skipped.
- **The 3B model can refuse answerable questions.** Retrieval may surface and
  cite the right chunk while the model still declines, especially when the
  question needs an inference beyond the text (for example *"My screen is
  flickering, am I still covered?"*). The reliable phrasing on the demo corpus
  is *"When does my Dell laptop warranty expire?"* Structured fact extraction
  (see roadmap) is the planned fix.
- **Cold model load can look like a failure.** See "Warm the model" above.
- **Vector search is noisy on the demo corpus,** because 98 of its 103
  documents are near-identical filler text. The relevant chunk still lands in
  the top 4 for well-formed questions.
- **No streaming.** Chat returns the full answer as JSON.
- **`open` / `reveal` are unverified on a real desktop.** The citation viewer
  always shows the path and quote, so it degrades gracefully if they fail.

### Repository hygiene

`node_modules/`, `__pycache__/` and `vault/*` are git-ignored and untracked.
Run `npm install` in `ui/` on your own machine.

Always create your own virtualenv rather than reusing any environment from a
clone.

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
