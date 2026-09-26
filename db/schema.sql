-- LifeVault S1 schema.
--
-- Frozen table shapes for S1. Later sessions may ALTER TABLE to add
-- nullable/optional columns but must not rename or drop existing columns.
--
-- Note on vectors: the `chunks_vec` virtual table (sqlite-vec) is NOT
-- created here because its column width depends on the configured
-- embedding dimension (see config.py: EMBEDDING_DIMENSION). It is created
-- programmatically by db/init_db.py so the dimension is never hard-coded
-- in SQL. If the sqlite-vec extension isn't available on a machine, init
-- skips that table with a warning and the rest of the schema still works.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- index_roots: folders the user has granted LifeVault permission to scan
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS index_roots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    path                TEXT NOT NULL UNIQUE,
    enabled             INTEGER NOT NULL DEFAULT 1,   -- 0/1
    exclude_patterns    TEXT NOT NULL DEFAULT '[]',   -- JSON array of glob strings
    granted_at          TEXT,                          -- ISO-8601 UTC, when consent was granted
    paused              INTEGER NOT NULL DEFAULT 0,    -- 0/1, independent of `enabled`
    paused_at           TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------
-- documents: identity is the content hash (dedupes identical files that
-- live at different paths)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    content_hash        TEXT PRIMARY KEY,              -- sha256 of file bytes
    title                TEXT,
    doc_type             TEXT,                          -- e.g. 'pdf', 'docx', 'note'
    size_bytes           INTEGER,
    page_count           INTEGER,
    mime_type            TEXT,
    status                TEXT NOT NULL DEFAULT 'active', -- active|superseded|deleted
    first_seen_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------
-- file_locations: where a given content_hash currently lives on disk
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS file_locations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash        TEXT NOT NULL REFERENCES documents(content_hash) ON DELETE CASCADE,
    root_id              INTEGER REFERENCES index_roots(id) ON DELETE SET NULL,
    path                  TEXT NOT NULL,
    size_bytes            INTEGER,                     -- S2 cheap-change prefilter
    mtime_ns              INTEGER,                     -- nanosecond file mtime
    missing               INTEGER NOT NULL DEFAULT 0,   -- 0/1, set when the path no longer resolves
    last_verified_at      TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(content_hash, path)
);

-- ---------------------------------------------------------------------
-- index_state: singleton persisted worker status used by /api/index/status
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS index_state (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    state               TEXT NOT NULL DEFAULT 'idle',
    files_found         INTEGER NOT NULL DEFAULT 0,
    files_unique        INTEGER NOT NULL DEFAULT 0,
    files_duplicates    INTEGER NOT NULL DEFAULT 0,
    files_skipped       INTEGER NOT NULL DEFAULT 0,
    files_processed     INTEGER NOT NULL DEFAULT 0,
    last_run_at         TEXT,
    message             TEXT
);

INSERT OR IGNORE INTO index_state (id) VALUES (1);

-- ---------------------------------------------------------------------
-- chunks: retrieval units belonging to a document
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash        TEXT NOT NULL REFERENCES documents(content_hash) ON DELETE CASCADE,
    chunk_index          INTEGER NOT NULL,             -- ordinal within the document
    text                  TEXT NOT NULL,
    page                  INTEGER,
    position               INTEGER,                     -- char offset or other locator, future-proofed
    superseded             INTEGER NOT NULL DEFAULT 0,   -- 0/1, set when a re-index replaces this chunk
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------
-- facts: normalized structured facts extracted from documents
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS facts (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    type                   TEXT NOT NULL,                -- e.g. 'policy_number', 'expiry_date'
    field                   TEXT NOT NULL,                -- human label, e.g. 'Policy Number'
    value                   TEXT,                          -- raw extracted value
    norm_value              TEXT,                          -- normalized/canonical value
    source_document_hash    TEXT REFERENCES documents(content_hash) ON DELETE SET NULL,
    source_chunk_id          INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
    source_quote              TEXT,                         -- verbatim supporting quote
    user_corrected             INTEGER NOT NULL DEFAULT 0,   -- 0/1
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------
-- proposals: actions the agent wants to take, pending human approval
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS proposals (
    id                        TEXT PRIMARY KEY,             -- uuid4 string
    tool                        TEXT NOT NULL,
    parameters                  TEXT NOT NULL DEFAULT '{}',   -- JSON object
    rationale                    TEXT,
    evidence_document_hashes      TEXT NOT NULL DEFAULT '[]',   -- JSON array of content_hash
    status                         TEXT NOT NULL DEFAULT 'pending', -- pending|approved|denied|executed|error
    decision                       TEXT,                          -- free-text note from the approver
    decided_at                     TEXT,
    created_at                     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------
-- memory: last-decision memory the agent can consult later
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    key                   TEXT NOT NULL UNIQUE,
    last_decision          TEXT,                          -- e.g. 'approved', 'denied'
    context                  TEXT NOT NULL DEFAULT '{}',   -- JSON object, free-form
    updated_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------
-- audit_log: append-only, hash-chained. This is the ONE real S1 feature.
-- Rows are never updated or deleted by application code.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    event          TEXT NOT NULL,
    payload         TEXT NOT NULL,                 -- canonical JSON (sorted keys, no whitespace)
    ts               TEXT NOT NULL,                 -- ISO-8601 UTC
    prev_hash         TEXT NOT NULL,                 -- row_hash of the previous row, or 64 zeros for the first row
    row_hash           TEXT NOT NULL                  -- sha256(prev_hash | event | ts | payload)
);

-- ---------------------------------------------------------------------
-- FTS5 full-text index over chunk text (external-content table, kept in
-- sync with `chunks` via triggers so later sessions get search for free)
-- ---------------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    content='chunks',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS chunks_fts_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.id, old.text);
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;

-- ---------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_file_locations_content_hash ON file_locations(content_hash);
CREATE INDEX IF NOT EXISTS idx_file_locations_root_id ON file_locations(root_id);
CREATE INDEX IF NOT EXISTS idx_file_locations_path ON file_locations(path);
CREATE INDEX IF NOT EXISTS idx_chunks_content_hash ON chunks(content_hash);
CREATE INDEX IF NOT EXISTS idx_facts_source_document_hash ON facts(source_document_hash);
CREATE INDEX IF NOT EXISTS idx_facts_type_field ON facts(type, field);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
CREATE INDEX IF NOT EXISTS idx_audit_log_event ON audit_log(event);
