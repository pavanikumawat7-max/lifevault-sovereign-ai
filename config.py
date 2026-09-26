"""LifeVault configuration.

Single source of truth for runtime configuration. Everything is read from
environment variables (optionally loaded from a local `.env` file), with
sane defaults so the project runs out of the box in fixture mode.

Deliberately implemented with the standard library + python-dotenv only
(no pydantic) so config loading has zero external dependencies and can be
imported by every other module -- including ones that must stay lightweight.

IMPORTANT: `embedding_dimension` is the single source of truth for vector
size. Nothing else in the codebase should hard-code a dimension; read it
from `get_config().embedding_dimension` instead.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a listed dependency
    load_dotenv = None  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent

# Defaults live in one place so both the dataclass and the env-loader agree.
DEFAULTS = {
    "database_path": str(REPO_ROOT / "data" / "lifevault.db"),
    "vault_dir": str(REPO_ROOT / "vault"),
    "demo_data_dir": str(REPO_ROOT / "demo-data"),
    "model_name": "llama3.2",
    "embedding_model_name": "nomic-embed-text",
    "embedding_dimension": 768,
    "ollama_host": "http://localhost:11434",
    "max_upload_size_mb": 50,
    "max_chunk_chars": 2000,
    "use_fixtures": True,
    "api_host": "127.0.0.1",
    "api_port": 8000,
    "ui_dev_port": 5173,
    "cors_origins": "http://localhost:5173",
    "log_level": "INFO",
}

_ENV_LOADED = False


def _ensure_env_loaded() -> None:
    """Load `.env` (if present) exactly once. Never overrides real env vars."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    if load_dotenv is not None:
        load_dotenv(dotenv_path=REPO_ROOT / ".env", override=False)
    _ENV_LOADED = True


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _get_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _get_str(name: str, default: str) -> str:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return val


@dataclass(frozen=True)
class Config:
    """Typed, immutable snapshot of LifeVault configuration."""

    database_path: str = DEFAULTS["database_path"]
    vault_dir: str = DEFAULTS["vault_dir"]
    demo_data_dir: str = DEFAULTS["demo_data_dir"]

    model_name: str = DEFAULTS["model_name"]
    embedding_model_name: str = DEFAULTS["embedding_model_name"]
    embedding_dimension: int = DEFAULTS["embedding_dimension"]
    ollama_host: str = DEFAULTS["ollama_host"]

    max_upload_size_mb: int = DEFAULTS["max_upload_size_mb"]
    max_chunk_chars: int = DEFAULTS["max_chunk_chars"]

    use_fixtures: bool = DEFAULTS["use_fixtures"]

    api_host: str = DEFAULTS["api_host"]
    api_port: int = DEFAULTS["api_port"]
    ui_dev_port: int = DEFAULTS["ui_dev_port"]
    cors_origins: str = DEFAULTS["cors_origins"]

    log_level: str = DEFAULTS["log_level"]


def load_config() -> Config:
    """Build a fresh `Config` from the current environment."""
    _ensure_env_loaded()
    return Config(
        database_path=_get_str("LIFEVAULT_DB_PATH", DEFAULTS["database_path"]),
        vault_dir=_get_str("LIFEVAULT_VAULT_DIR", DEFAULTS["vault_dir"]),
        demo_data_dir=_get_str("LIFEVAULT_DEMO_DATA_DIR", DEFAULTS["demo_data_dir"]),
        model_name=_get_str("LIFEVAULT_MODEL_NAME", DEFAULTS["model_name"]),
        embedding_model_name=_get_str(
            "LIFEVAULT_EMBEDDING_MODEL_NAME", DEFAULTS["embedding_model_name"]
        ),
        embedding_dimension=_get_int(
            "LIFEVAULT_EMBEDDING_DIM", DEFAULTS["embedding_dimension"]
        ),
        ollama_host=_get_str("LIFEVAULT_OLLAMA_HOST", DEFAULTS["ollama_host"]),
        max_upload_size_mb=_get_int(
            "LIFEVAULT_MAX_UPLOAD_SIZE_MB", DEFAULTS["max_upload_size_mb"]
        ),
        max_chunk_chars=_get_int(
            "LIFEVAULT_MAX_CHUNK_CHARS", DEFAULTS["max_chunk_chars"]
        ),
        use_fixtures=_get_bool("LIFEVAULT_USE_FIXTURES", DEFAULTS["use_fixtures"]),
        api_host=_get_str("LIFEVAULT_API_HOST", DEFAULTS["api_host"]),
        api_port=_get_int("LIFEVAULT_API_PORT", DEFAULTS["api_port"]),
        ui_dev_port=_get_int("LIFEVAULT_UI_DEV_PORT", DEFAULTS["ui_dev_port"]),
        cors_origins=_get_str("LIFEVAULT_CORS_ORIGINS", DEFAULTS["cors_origins"]),
        log_level=_get_str("LIFEVAULT_LOG_LEVEL", DEFAULTS["log_level"]),
    )


_config_instance: Optional[Config] = None


def get_config() -> Config:
    """Return the process-wide cached Config, loading it on first use."""
    global _config_instance
    if _config_instance is None:
        _config_instance = load_config()
    return _config_instance


def reset_config_cache() -> None:
    """Clear the cached Config. Mainly for tests that mutate env vars."""
    global _config_instance
    _config_instance = None
