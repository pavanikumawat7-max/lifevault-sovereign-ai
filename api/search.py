"""Hybrid retrieval over the S2 index (S3).

Two independent rankers, fused:

  * lexical  -- FTS5 BM25 over `chunks_fts`, top 20
  * semantic -- sqlite-vec KNN over `chunks_vec`, top 20
  * fused    -- Reciprocal Rank Fusion, score = sum(1 / (RRF_K + rank))

This module is read-only: it consumes exactly the storage contract S2
established (`chunks`, `chunks_fts`, `chunks_vec`, `documents`,
`file_locations`) and never writes, so searching can never mutate the
index.

Two behaviors worth knowing about before changing anything here:

  * Either ranker may legitimately return nothing -- no FTS match, no
    `chunks_vec` table (sqlite-vec not installed), or an unreachable
    embedding model. RRF over one list still produces a sane ordering, so
    search degrades instead of failing. It only returns [] when *both*
    rankers come back empty.
  * Fixture mode (`LIFEVAULT_USE_FIXTURES=true`) makes `llm.embed` return
    a zero vector, so every stored vector is equidistant and the semantic
    arm carries no signal. That is expected, not a bug: fixture mode is
    for running without a model, and the lexical arm still ranks properly.
"""
from __future__ import annotations

import os
import re
import sqlite3
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import llm
from db.connect import connect

# --- Tunables ------------------------------------------------------------
# RRF constant from the handover plan: score = sum(1 / (60 + rank)).
RRF_K = 60
LEXICAL_LIMIT = 20
VECTOR_LIMIT = 20
# How many fused chunks the answer prompt gets. Small on purpose, and
# measured rather than guessed: on the dev laptop (M1 Air, 8 GB) going from
# 6 chunks to 4 cut the prompt from ~4.4k to ~2.7k characters and roughly
# halved per-answer latency, with no loss on the eval set -- the relevant
# chunk is inside the top 4 for every question in scripts/eval.py. A local
# 3B model also degrades as the context fills with near-miss chunks.
DEFAULT_TOP_K = 4

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/'\-]*")
_WS_RE = re.compile(r"\s+")

# Standard English function words. Removing them matters more than it
# looks: the match expression is an OR, so every term the user happens to
# use ("am", "still", "is") pulls in unrelated documents that merely share
# that word, diluting BM25's rare-term weighting. Falling back to the
# unfiltered tokens (see build_match_query) protects questions made
# entirely of function words.
_STOPWORDS = frozenset(
    """
    a about above after again against all also am an and any are aren't as at
    be because been before being below between both but by can can't cannot
    could couldn't did didn't do does doesn't doing don't down during each few
    for from further had hadn't has hasn't have haven't having he her here
    hers herself him himself his how i i'd i'll i'm i've if in into is isn't
    it it's its itself just me more most my myself no nor not of off on once
    only or other ought our ours ourselves out over own same shan't she
    should shouldn't so some still such than that the their theirs them
    themselves then there these they this those through to too under until up
    very was wasn't we were weren't what when where which while who whom why
    will with won't would wouldn't you your yours yourself yourselves
    """.split()
)


@dataclass(frozen=True)
class RetrievedChunk:
    """One fused search hit, carrying everything a citation needs."""

    chunk_id: int
    content_hash: str
    text: str
    page: Optional[int]
    chunk_index: int
    abs_path: str
    #: Every known on-disk location of this document, including `abs_path`.
    locations: List[Dict[str, Any]] = field(default_factory=list)
    title: Optional[str] = None
    score: float = 0.0
    lexical_rank: Optional[int] = None
    vector_rank: Optional[int] = None

    @property
    def also_found_at(self) -> List[str]:
        """Other paths holding byte-identical content ("also found at")."""
        return [
            location["path"]
            for location in self.locations
            if location["path"] != self.abs_path
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "content_hash": self.content_hash,
            "text": self.text,
            "page": self.page,
            "chunk_index": self.chunk_index,
            "abs_path": self.abs_path,
            "locations": [dict(location) for location in self.locations],
            "also_found_at": self.also_found_at,
            "title": self.title,
            "score": self.score,
            "lexical_rank": self.lexical_rank,
            "vector_rank": self.vector_rank,
        }


# ---------------------------------------------------------------------
# Query preparation
# ---------------------------------------------------------------------


def build_match_query(text: str) -> str:
    """Turn free-form user text into a safe FTS5 MATCH expression.

    Every term is double-quoted, which is what makes this safe: quoted
    FTS5 terms are literals, so punctuation, hyphens and reserved words in
    the user's question ("NOT", "AND", "*", "-") can never be interpreted
    as query syntax. Terms are OR-ed because BM25 wants recall first and
    then sorts by score -- AND-ing a natural-language question usually
    matches nothing at all.

    Returns "" when the question has no usable terms; callers treat that
    as "no lexical results".
    """
    tokens = [token.strip("._/'-").lower() for token in _TOKEN_RE.findall(text)]
    tokens = [token for token in tokens if len(token) > 1]
    # Fall back to the unfiltered tokens if stopword removal empties the
    # query (e.g. "what is it about").
    terms = [token for token in tokens if token not in _STOPWORDS] or tokens
    if not terms:
        return ""

    ordered: List[str] = []
    seen: Set[str] = set()
    for term in terms:
        if term not in seen:
            seen.add(term)
            ordered.append(term)
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in ordered)


# ---------------------------------------------------------------------
# The two rankers
# ---------------------------------------------------------------------


def lexical_search(
    conn: sqlite3.Connection, query: str, limit: int = LEXICAL_LIMIT
) -> List[int]:
    """FTS5 BM25 ranking, best first. Superseded chunks are excluded.

    `bm25()` returns a more-negative score for a better match, so plain
    ascending ORDER BY is already best-first.
    """
    match = build_match_query(query)
    if not match:
        return []
    try:
        rows = conn.execute(
            """
            SELECT chunks.id AS id
            FROM chunks_fts
            JOIN chunks ON chunks.id = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
              AND chunks.superseded = 0
            ORDER BY bm25(chunks_fts)
            LIMIT ?
            """,
            (match, limit),
        ).fetchall()
    except sqlite3.Error:
        # A malformed MATCH expression or a missing FTS table must not take
        # the whole search down -- the semantic arm can still answer.
        return []
    return [row["id"] for row in rows]


def vector_search(
    conn: sqlite3.Connection, query: str, limit: int = VECTOR_LIMIT
) -> List[int]:
    """sqlite-vec KNN ranking, nearest first. Superseded chunks excluded.

    Returns [] (rather than raising) when there is no `chunks_vec` table,
    when the embedding model is unreachable, or when the query vector's
    width does not match the indexed width -- all of which are
    configuration facts, not request errors.
    """
    if not has_vector_index(conn):
        return []
    try:
        vector = llm.embed(query)
    except Exception:  # noqa: BLE001 - llm.embed's failure is non-fatal here
        return []
    if not vector:
        return []

    blob = _serialize(vector)
    # Over-fetch, because superseded chunks are filtered *after* the KNN
    # scan and would otherwise eat slots out of the top `limit`.
    over_fetch = limit * 2
    rows: Sequence[sqlite3.Row] = ()
    for sql in (
        "SELECT chunk_id FROM chunks_vec "
        "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        "SELECT chunk_id FROM chunks_vec "
        "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
    ):
        try:
            rows = conn.execute(sql, (blob, over_fetch)).fetchall()
            break
        except sqlite3.Error:
            continue
    else:
        return []

    return _drop_superseded(conn, [row["chunk_id"] for row in rows])[:limit]


# ---------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------


def reciprocal_rank_fusion(
    rankings: Iterable[Sequence[int]], k: int = RRF_K
) -> Dict[int, float]:
    """Reciprocal Rank Fusion: score = sum over rankings of 1 / (k + rank).

    `rank` is 1-based. A chunk found by both rankers scores higher than one
    found by either alone, which is the whole point of running both.
    """
    scores: Dict[int, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def hybrid_search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    lexical_limit: int = LEXICAL_LIMIT,
    vector_limit: int = VECTOR_LIMIT,
) -> List[RetrievedChunk]:
    """Run both rankers, fuse with RRF, and return the top `top_k` chunks.

    Duplicate content is collapsed: two chunks with the same
    `content_hash` and the same text yield one result, and every known
    location of that content is attached to it (so a document sitting in
    two folders is one citation with an "also found at", not two hits).
    """
    if not query or not query.strip():
        return []

    owns_connection = conn is None
    conn = conn if conn is not None else connect(db_path)
    try:
        lexical = lexical_search(conn, query, lexical_limit)
        semantic = vector_search(conn, query, vector_limit)
        scores = reciprocal_rank_fusion([lexical, semantic])
        if not scores:
            return []

        lexical_ranks = {chunk_id: i for i, chunk_id in enumerate(lexical, start=1)}
        vector_ranks = {chunk_id: i for i, chunk_id in enumerate(semantic, start=1)}
        # Ties broken by lexical rank, then chunk id, so ordering is stable
        # across runs (important for the eval table being reproducible).
        ordered = sorted(
            scores,
            key=lambda chunk_id: (
                -scores[chunk_id],
                lexical_ranks.get(chunk_id, len(scores) + 1),
                chunk_id,
            ),
        )

        rows = _load_chunks(conn, ordered)
        locations = _load_locations(
            conn, {row["content_hash"] for row in rows.values()}
        )

        results: List[RetrievedChunk] = []
        seen_content: Set[tuple] = set()
        for chunk_id in ordered:
            row = rows.get(chunk_id)
            if row is None:
                continue
            dedupe_key = (row["content_hash"], _normalize(row["text"]))
            if dedupe_key in seen_content:
                continue
            seen_content.add(dedupe_key)

            document_locations = locations.get(row["content_hash"], [])
            results.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    content_hash=row["content_hash"],
                    text=row["text"],
                    page=row["page"],
                    chunk_index=row["chunk_index"],
                    abs_path=_primary_path(document_locations),
                    locations=document_locations,
                    title=row["title"],
                    score=scores[chunk_id],
                    lexical_rank=lexical_ranks.get(chunk_id),
                    vector_rank=vector_ranks.get(chunk_id),
                )
            )
            if len(results) >= top_k:
                break
        return results
    finally:
        if owns_connection:
            conn.close()


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def has_vector_index(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='chunks_vec'"
        ).fetchone()
        is not None
    )


def _drop_superseded(conn: sqlite3.Connection, chunk_ids: Sequence[int]) -> List[int]:
    """Keep only live chunk ids, preserving the incoming order."""
    if not chunk_ids:
        return []
    placeholders = ",".join("?" * len(chunk_ids))
    live = {
        row["id"]
        for row in conn.execute(
            f"SELECT id FROM chunks WHERE superseded = 0 AND id IN ({placeholders})",
            tuple(chunk_ids),
        )
    }
    return [chunk_id for chunk_id in chunk_ids if chunk_id in live]


def _load_chunks(
    conn: sqlite3.Connection, chunk_ids: Sequence[int]
) -> Dict[int, sqlite3.Row]:
    if not chunk_ids:
        return {}
    placeholders = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        f"""
        SELECT chunks.id AS id, chunks.content_hash, chunks.chunk_index,
               chunks.text, chunks.page, documents.title AS title
        FROM chunks
        LEFT JOIN documents ON documents.content_hash = chunks.content_hash
        WHERE chunks.superseded = 0 AND chunks.id IN ({placeholders})
        """,
        tuple(chunk_ids),
    ).fetchall()
    return {row["id"]: row for row in rows}


def _load_locations(
    conn: sqlite3.Connection, content_hashes: Set[str]
) -> Dict[str, List[Dict[str, Any]]]:
    """All on-disk locations per content hash, present ones first."""
    if not content_hashes:
        return {}
    placeholders = ",".join("?" * len(content_hashes))
    rows = conn.execute(
        f"""
        SELECT content_hash, path, missing, last_verified_at
        FROM file_locations
        WHERE content_hash IN ({placeholders})
        ORDER BY missing, id
        """,
        tuple(content_hashes),
    ).fetchall()
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["content_hash"], []).append(
            {
                "path": os.path.abspath(row["path"]),
                "missing": bool(row["missing"]),
                "last_verified_at": row["last_verified_at"],
            }
        )
    return grouped


def _primary_path(locations: Sequence[Dict[str, Any]]) -> str:
    """The path a citation should open: the first one still on disk."""
    for location in locations:
        if not location["missing"]:
            return location["path"]
    return locations[0]["path"] if locations else ""


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().casefold()


def _serialize(vector: Sequence[float]) -> bytes:
    """Little-endian float32 blob -- the same encoding worker/index.py writes."""
    return struct.pack(f"<{len(vector)}f", *vector)
