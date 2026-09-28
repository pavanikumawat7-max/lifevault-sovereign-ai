"""Vault path safety, shared by every tool (S7).

One rule, enforced in one place: a tool may only ever write to a path that
resolves inside the configured vault directory. Filenames are rebuilt from
a slug of the requested text rather than used as given, so a parameter that
came out of a document -- untrusted data -- cannot contain `..`, an
absolute path, a symlink hop, or a NUL byte and escape.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import get_config

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


class VaultPathError(Exception):
    """Raised when a write would land outside the vault."""


def vault_root() -> Path:
    root = Path(get_config().vault_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def slugify(text: str, fallback: str = "untitled", max_length: int = 60) -> str:
    """Filesystem-safe slug. Never returns "", ".", ".." or a hidden name."""
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_STRIP_RE.sub("-", ascii_only).strip("-")[:max_length].strip("-.")
    return slug or fallback


def vault_path(subdir: str, filename: str) -> Path:
    """Build `<vault>/<subdir>/<filename>` and prove it stays inside.

    The containment check is done on the *resolved* path, so it also catches
    a symlink inside the vault pointing out of it. Directories are created
    only after the check passes.
    """
    root = vault_root()
    candidate = (root / subdir / filename).resolve()
    if candidate == root or root not in candidate.parents:
        raise VaultPathError(
            f"refusing to write outside the vault: {candidate} is not under {root}"
        )
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def unique_path(path: Path) -> Path:
    """Never overwrite: append -2, -3, ... if the name is taken."""
    if not path.exists():
        return path
    for counter in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise VaultPathError(f"too many files named like {path.name}")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def relative_to_vault(path: Path) -> str:
    try:
        return str(path.relative_to(vault_root()))
    except ValueError:  # pragma: no cover - vault_path already guarantees this
        return str(path)
