"""Read-only filesystem discovery, prefiltering, and SHA-256 deduplication."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import mimetypes
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from config import get_config
from db.connect import connect
from worker.worker import ScanResult

INCOMPLETE_SUFFIXES = {".part", ".crdownload", ".tmp"}
VIDEO_SUFFIXES = {
    ".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm", ".wmv"
}
EXECUTABLE_SUFFIXES = {
    ".app", ".bat", ".bin", ".cmd", ".com", ".dll", ".dmg", ".exe", ".msi",
    ".scr", ".sh", ".so"
}
# S5 addition: images are supported now that OCR exists. DOCX stays out --
# it needs a different extractor, not OCR, and is on the plan's cut list.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
SUPPORTED_SUFFIXES = {".pdf"} | IMAGE_SUFFIXES
SKIP_DIR_NAMES = {".git", "node_modules"}


@dataclass(frozen=True)
class ScannedDocument:
    content_hash: str
    path: str
    needs_processing: bool


@dataclass
class ScanBatch:
    result: ScanResult
    documents: list[ScannedDocument] = field(default_factory=list)
    duplicates: int = 0
    skipped: int = 0


def scan_root(root_id: int, db_path: str | None = None) -> ScanBatch:
    """Scan one approved root without opening any source file for writing."""
    cfg = get_config()
    conn = connect(db_path)
    try:
        root = conn.execute(
            "SELECT * FROM index_roots WHERE id=? AND enabled=1", (root_id,)
        ).fetchone()
        if root is None:
            raise ValueError(f"Root {root_id} is not approved")
        if root["paused"]:
            return ScanBatch(ScanResult(root_id=root_id))
        root_path = Path(root["path"])
        if not root_path.is_dir():
            raise FileNotFoundError(f"Approved root does not exist: {root_path}")
        patterns = _patterns(root["exclude_patterns"])
    finally:
        conn.close()

    result = ScanResult(root_id=root_id)
    batch = ScanBatch(result=result)
    seen_paths: set[str] = set()
    max_bytes = cfg.max_upload_size_mb * 1024 * 1024

    for path in _walk(root_path, _runtime_paths(cfg)):
        try:
            stat = path.stat()
        except OSError:
            batch.skipped += 1
            continue
        result.files_found += 1
        if _should_skip(path, root_path, patterns, stat.st_size, max_bytes):
            batch.skipped += 1
            continue

        normalized = str(path.resolve())
        seen_paths.add(normalized)
        conn = connect(db_path)
        try:
            previous = conn.execute(
                """
                SELECT content_hash, size_bytes, mtime_ns
                FROM file_locations
                WHERE root_id=? AND path=? AND missing=0
                ORDER BY id DESC LIMIT 1
                """,
                (root_id, normalized),
            ).fetchone()
        finally:
            conn.close()

        if (
            previous is not None
            and previous["size_bytes"] == stat.st_size
            and previous["mtime_ns"] == stat.st_mtime_ns
        ):
            _touch_location(db_path, root_id, normalized)
            batch.documents.append(
                ScannedDocument(previous["content_hash"], normalized, False)
            )
            continue

        content_hash = _sha256(path)
        conn = connect(db_path)
        try:
            known = conn.execute(
                "SELECT 1 FROM documents WHERE content_hash=?", (content_hash,)
            ).fetchone()
            has_chunks = conn.execute(
                "SELECT 1 FROM chunks WHERE content_hash=? LIMIT 1", (content_hash,)
            ).fetchone()
            now = _utcnow()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO documents
                    (content_hash, title, doc_type, size_bytes, mime_type, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(content_hash) DO UPDATE SET
                    last_seen_at=excluded.last_seen_at,
                    status='active'
                """,
                (
                    content_hash,
                    path.name,
                    path.suffix.lower().lstrip("."),
                    stat.st_size,
                    mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    now,
                ),
            )
            old_hashes = [
                row["content_hash"]
                for row in conn.execute(
                    "SELECT content_hash FROM file_locations WHERE root_id=? AND path=?",
                    (root_id, normalized),
                )
                if row["content_hash"] != content_hash
            ]
            conn.execute(
                "DELETE FROM file_locations WHERE root_id=? AND path=? AND content_hash<>?",
                (root_id, normalized, content_hash),
            )
            conn.execute(
                """
                INSERT INTO file_locations
                    (content_hash, root_id, path, size_bytes, mtime_ns,
                     missing, last_verified_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(content_hash, path) DO UPDATE SET
                    root_id=excluded.root_id,
                    size_bytes=excluded.size_bytes,
                    mtime_ns=excluded.mtime_ns,
                    missing=0,
                    last_verified_at=excluded.last_verified_at
                """,
                (content_hash, root_id, normalized, stat.st_size, stat.st_mtime_ns, now),
            )
            for old_hash in old_hashes:
                if conn.execute(
                    "SELECT 1 FROM file_locations WHERE content_hash=? LIMIT 1",
                    (old_hash,),
                ).fetchone() is None:
                    if conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='chunks_vec'"
                    ).fetchone():
                        chunk_ids = [
                            row["id"]
                            for row in conn.execute(
                                "SELECT id FROM chunks WHERE content_hash=?",
                                (old_hash,),
                            )
                        ]
                        conn.executemany(
                            "DELETE FROM chunks_vec WHERE chunk_id=?",
                            [(chunk_id,) for chunk_id in chunk_ids],
                        )
                    conn.execute(
                        "DELETE FROM documents WHERE content_hash=?", (old_hash,)
                    )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

        if known:
            batch.duplicates += 1
        else:
            result.files_new += 1
        if previous is not None and previous["content_hash"] != content_hash:
            result.files_changed += 1
        batch.documents.append(
            ScannedDocument(content_hash, normalized, has_chunks is None)
        )

    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, path FROM file_locations WHERE root_id=? AND missing=0",
            (root_id,),
        ).fetchall()
        missing_ids = [row["id"] for row in rows if row["path"] not in seen_paths]
        if missing_ids:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                "UPDATE file_locations SET missing=1 WHERE id=?",
                [(value,) for value in missing_ids],
            )
            conn.execute("COMMIT")
        result.files_missing = len(missing_ids)
    finally:
        conn.close()
    return batch


def _walk(root: Path, runtime_paths: tuple[Path, ...]) -> Iterable[Path]:
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    path = Path(entry.path)
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name in SKIP_DIR_NAMES or _inside_any(path, runtime_paths):
                                continue
                            stack.append(path)
                        elif entry.is_file(follow_symlinks=False):
                            yield path
                    except OSError:
                        continue
        except OSError:
            continue


def _should_skip(
    path: Path,
    root: Path,
    patterns: list[str],
    size: int,
    max_bytes: int,
) -> bool:
    suffix = path.suffix.lower()
    rel = str(path.relative_to(root))
    return (
        suffix in INCOMPLETE_SUFFIXES
        or suffix in VIDEO_SUFFIXES
        or suffix in EXECUTABLE_SUFFIXES
        or suffix not in SUPPORTED_SUFFIXES
        or size > max_bytes
        or any(fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(path.name, pattern)
               for pattern in patterns)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _patterns(raw: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def _runtime_paths(cfg) -> tuple[Path, ...]:
    # The vault is generated output. The database itself is a file and is
    # naturally rejected by the supported-extension filter; excluding its
    # whole parent would incorrectly hide a user-approved sibling folder.
    return (Path(cfg.vault_dir).expanduser().resolve(),)


def _inside_any(path: Path, parents: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    return any(resolved == parent or parent in resolved.parents for parent in parents)


def _touch_location(db_path: str | None, root_id: int, path: str) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            "UPDATE file_locations SET missing=0, last_verified_at=? "
            "WHERE root_id=? AND path=?",
            (_utcnow(), root_id, path),
        )
    finally:
        conn.close()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()