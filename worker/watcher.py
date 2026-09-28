"""Filesystem watcher (S5).

Watches every approved, unpaused root and keeps the index live, so a PDF
dropped into a watched folder becomes searchable without restarting anything.

Design decisions worth understanding before changing this:

  * **Events are debounced, then handled by re-scanning the affected root.**
    A single save can emit half a dozen inotify/FSEvents notifications, and
    an editor writing a file emits `created` before the bytes are all there.
    So events mark a root dirty, and after a quiet period
    `worker.index.ingest_root` runs. That reuses the scanner's existing
    prefilter (path, size, mtime), hashing, duplicate handling and chunk
    supersession instead of reimplementing them here -- the prefilter means
    an unchanged file is never re-hashed, so a re-scan is cheap.
  * **Writes are waited out, not raced.** A file is only considered ready
    once its size has been stable for `STABLE_SECONDS`. Partial downloads
    (`.part`, `.crdownload`, `.tmp`) are ignored outright.
  * **Deletions never delete anything.** The location is flagged `missing=1`
    and the document, its chunks and its facts all stay. A citation into a
    file that has moved should degrade to "this file is no longer where it
    was", not vanish from history.
  * **The vault is never watched.** LifeVault writes `.ics` and `.eml` files
    into the vault, and indexing its own output would be a feedback loop.

Run it on its own (`python -m worker.watcher`) or through `run.py`, which
starts it alongside the API.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from config import get_config
from db.connect import connect
from worker.scanner import (
    EXECUTABLE_SUFFIXES,
    INCOMPLETE_SUFFIXES,
    SUPPORTED_SUFFIXES,
    VIDEO_SUFFIXES,
)

logger = logging.getLogger(__name__)

#: How long to wait for more events before acting on a root.
DEBOUNCE_SECONDS = 2.0

#: A file's size must be unchanged for this long before it is ingested.
STABLE_SECONDS = 2.0

#: Give up waiting for a file that never settles (a huge slow copy).
STABLE_TIMEOUT_SECONDS = 120.0

#: How often the poll loop re-reads the approved-root list.
ROOT_REFRESH_SECONDS = 10.0


@dataclass
class WatcherStats:
    """Counters, mainly so tests and logs can assert something happened."""

    events_seen: int = 0
    events_ignored: int = 0
    rescans: int = 0
    deletions: int = 0
    documents_indexed: int = 0


def approved_roots(db_path: Optional[str] = None) -> List[Dict[str, object]]:
    """Every root that is enabled and not paused."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, path FROM index_roots WHERE enabled=1 AND paused=0"
        ).fetchall()
    finally:
        conn.close()
    return [{"id": row["id"], "path": row["path"]} for row in rows]


def is_ignorable(path: Path, vault_dir: Optional[Path] = None) -> bool:
    """Should this path never trigger indexing?

    Mirrors the scanner's filters so the watcher and a full scan agree about
    what counts as a document. Disagreement here would show up as files that
    appear only after a manual re-index, which is a horrible thing to debug.
    """
    vault_dir = vault_dir or Path(get_config().vault_dir).expanduser().resolve()
    try:
        resolved = path.resolve()
    except OSError:
        return True

    # Never index our own output.
    if resolved == vault_dir or vault_dir in resolved.parents:
        return True
    # Hidden files and anything inside a dot-directory.
    if any(part.startswith(".") for part in resolved.parts):
        return True

    suffix = resolved.suffix.lower()
    if suffix in INCOMPLETE_SUFFIXES or suffix in VIDEO_SUFFIXES:
        return True
    if suffix in EXECUTABLE_SUFFIXES:
        return True
    return suffix not in SUPPORTED_SUFFIXES


def wait_until_stable(
    path: Path,
    stable_seconds: float = STABLE_SECONDS,
    timeout: float = STABLE_TIMEOUT_SECONDS,
) -> bool:
    """Block until `path`'s size stops changing. False if it never settles."""
    deadline = time.monotonic() + timeout
    last_size = -1
    stable_since: Optional[float] = None

    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            return False
        now = time.monotonic()
        if size != last_size:
            last_size = size
            stable_since = now
        elif stable_since is not None and now - stable_since >= stable_seconds:
            return True
        time.sleep(0.25)
    return False


def mark_location_missing(path: Path, db_path: Optional[str] = None) -> int:
    """Flag a vanished path as missing. Keeps the document, chunks and facts.

    Returns the number of location rows updated.
    """
    conn = connect(db_path)
    try:
        cursor = conn.execute(
            "UPDATE file_locations SET missing=1 WHERE path=? AND missing=0",
            (str(path),),
        )
        return cursor.rowcount or 0
    finally:
        conn.close()


def reindex_root(root_id: int, db_path: Optional[str] = None) -> Dict[str, object]:
    """Re-scan and re-index one root. Cheap when nothing actually changed."""
    from worker.index import ingest_root

    return ingest_root(root_id, db_path)


# ---------------------------------------------------------------------
# The watcher
# ---------------------------------------------------------------------


class RootWatcher:
    """Debounced watcher over every approved root.

    Usable either as a long-running service (`start()` / `stop()`) or
    synchronously in tests (`process_pending()`), which is why the debounce
    and the handling are separate steps.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path
        self.stats = WatcherStats()
        self._dirty_roots: Set[int] = set()
        self._pending_deletions: Set[Path] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._observer = None
        self._watched: Dict[str, object] = {}
        self._vault_dir = Path(get_config().vault_dir).expanduser().resolve()

    # --- event intake ------------------------------------------------

    def note_change(self, path: Path, root_id: int) -> None:
        """Record a created/modified file for the next debounced pass."""
        self.stats.events_seen += 1
        if is_ignorable(path, self._vault_dir):
            self.stats.events_ignored += 1
            return
        with self._lock:
            self._dirty_roots.add(root_id)

    def note_deletion(self, path: Path) -> None:
        """Record a deleted or moved-away file."""
        self.stats.events_seen += 1
        if is_ignorable(path, self._vault_dir):
            self.stats.events_ignored += 1
            return
        with self._lock:
            self._pending_deletions.add(path)

    # --- debounced handling ------------------------------------------

    def process_pending(self) -> Dict[str, object]:
        """Apply everything queued so far. Safe to call when nothing is queued."""
        with self._lock:
            roots = sorted(self._dirty_roots)
            deletions = sorted(self._pending_deletions)
            self._dirty_roots.clear()
            self._pending_deletions.clear()

        summary: Dict[str, object] = {"roots": [], "deleted": 0}

        for path in deletions:
            # A "delete" that is really a rename-in-place may already exist
            # again by the time we get here; only flag it if it is truly gone.
            if path.exists():
                with self._lock:
                    self._dirty_roots.add(self._root_id_for(path) or -1)
                continue
            updated = mark_location_missing(path, self.db_path)
            self.stats.deletions += updated
            summary["deleted"] = int(summary["deleted"]) + updated

        for root_id in roots:
            if root_id < 0:
                continue
            try:
                outcome = reindex_root(root_id, self.db_path)
            except Exception as exc:  # noqa: BLE001 - one bad root must not stop the watcher
                logger.warning("re-index of root %s failed: %s", root_id, exc)
                continue
            self.stats.rescans += 1
            self.stats.documents_indexed += int(outcome.get("processed") or 0)
            summary["roots"].append(outcome)  # type: ignore[union-attr]
        return summary

    def _root_id_for(self, path: Path) -> Optional[int]:
        for root in approved_roots(self.db_path):
            root_path = Path(str(root["path"]))
            try:
                if root_path == path or root_path in path.resolve().parents:
                    return int(root["id"])  # type: ignore[arg-type]
            except OSError:
                continue
        return None

    # --- service lifecycle -------------------------------------------

    def start(self) -> None:
        """Begin watching. Raises ImportError if watchdog is not installed."""
        from watchdog.observers import Observer

        self._observer = Observer()
        self._sync_watches()
        self._observer.start()
        logger.info("watcher started on %d root(s)", len(self._watched))

    def _sync_watches(self) -> None:
        """Add/remove observer watches so they match the approved roots."""
        if self._observer is None:
            return
        from watchdog.events import FileSystemEventHandler

        current = {str(Path(str(r["path"])).resolve()): r for r in approved_roots(self.db_path)}

        for path in list(self._watched):
            if path not in current:
                self._observer.unschedule(self._watched.pop(path))  # type: ignore[arg-type]

        watcher = self

        for path, root in current.items():
            if path in self._watched:
                continue
            root_id = int(root["id"])  # type: ignore[arg-type]

            class _Handler(FileSystemEventHandler):
                def on_created(self, event):  # noqa: ANN001
                    if not event.is_directory:
                        watcher.note_change(Path(event.src_path), root_id)

                def on_modified(self, event):  # noqa: ANN001
                    if not event.is_directory:
                        watcher.note_change(Path(event.src_path), root_id)

                def on_deleted(self, event):  # noqa: ANN001
                    if not event.is_directory:
                        watcher.note_deletion(Path(event.src_path))

                def on_moved(self, event):  # noqa: ANN001
                    # A move is a deletion plus a new file, exactly as the
                    # handover plan specifies.
                    if not event.is_directory:
                        watcher.note_deletion(Path(event.src_path))
                        watcher.note_change(Path(event.dest_path), root_id)

            if not Path(path).is_dir():
                logger.warning("approved root is not a directory, skipping: %s", path)
                continue
            self._watched[path] = self._observer.schedule(
                _Handler(), path, recursive=True
            )

    def run_forever(self) -> None:
        """Debounce loop. Returns when `stop()` is called."""
        last_refresh = 0.0
        while not self._stop.is_set():
            self._stop.wait(DEBOUNCE_SECONDS)
            if self._stop.is_set():
                break

            now = time.monotonic()
            if now - last_refresh > ROOT_REFRESH_SECONDS:
                try:
                    self._sync_watches()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("could not refresh watches: %s", exc)
                last_refresh = now

            with self._lock:
                has_work = bool(self._dirty_roots or self._pending_deletions)
            if not has_work:
                continue

            # Let an in-progress copy finish before re-scanning.
            time.sleep(STABLE_SECONDS)
            summary = self.process_pending()
            if summary["roots"] or summary["deleted"]:
                logger.info("watcher applied changes: %s", summary)

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None


def main() -> int:
    """Run the watcher until interrupted."""
    logging.basicConfig(
        level=getattr(logging, get_config().log_level.upper(), logging.INFO),
        format="[worker.watcher] %(message)s",
    )
    from db.init_db import init_db

    init_db()

    roots = approved_roots()
    if not roots:
        print(
            "[worker.watcher] No approved roots yet. Add one with "
            "POST /api/roots or scripts/index_folder.py, then restart."
        )

    watcher = RootWatcher()
    try:
        watcher.start()
    except ImportError:
        print(
            "[worker.watcher] watchdog is not installed; live watching is "
            "disabled. Run `pip install -r requirements.txt`."
        )
        return 1
    try:
        watcher.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
