from config import Config, get_config, load_config, reset_config_cache


def test_config_defaults(monkeypatch):
    monkeypatch.delenv("LIFEVAULT_DB_PATH", raising=False)
    monkeypatch.delenv("LIFEVAULT_EMBEDDING_DIM", raising=False)
    cfg = load_config()
    assert isinstance(cfg, Config)
    assert cfg.embedding_dimension > 0
    assert cfg.database_path


def test_config_env_override(monkeypatch):
    monkeypatch.setenv("LIFEVAULT_DB_PATH", "/tmp/custom_lifevault.db")
    monkeypatch.setenv("LIFEVAULT_EMBEDDING_DIM", "1024")
    cfg = load_config()
    assert cfg.database_path == "/tmp/custom_lifevault.db"
    assert cfg.embedding_dimension == 1024


def test_use_fixtures_default_true(monkeypatch):
    monkeypatch.delenv("LIFEVAULT_USE_FIXTURES", raising=False)
    cfg = load_config()
    assert cfg.use_fixtures is True


def test_get_config_is_cached(monkeypatch):
    reset_config_cache()
    first = get_config()
    second = get_config()
    assert first is second
    reset_config_cache()
