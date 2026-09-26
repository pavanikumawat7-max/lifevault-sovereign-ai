import importlib


def test_chat_fixture_mode(monkeypatch):
    monkeypatch.setenv("LIFEVAULT_USE_FIXTURES", "true")
    from config import reset_config_cache

    reset_config_cache()
    import llm

    importlib.reload(llm)
    reply = llm.chat([{"role": "user", "content": "hi"}])
    assert isinstance(reply, str)
    assert len(reply) > 0


def test_embed_fixture_mode_matches_configured_dimension(monkeypatch):
    monkeypatch.setenv("LIFEVAULT_USE_FIXTURES", "true")
    from config import get_config, reset_config_cache

    reset_config_cache()
    import llm

    importlib.reload(llm)
    vec = llm.embed("hello world")
    assert len(vec) == get_config().embedding_dimension


def test_structured_output_fixture_mode(monkeypatch):
    monkeypatch.setenv("LIFEVAULT_USE_FIXTURES", "true")
    from config import reset_config_cache

    reset_config_cache()
    import llm

    importlib.reload(llm)
    result = llm.structured_output("extract a name", "JSON with a name field")
    assert result["stub"] is True


def test_is_model_available_false_when_nothing_running(monkeypatch):
    monkeypatch.setenv("LIFEVAULT_USE_FIXTURES", "false")
    monkeypatch.setenv("LIFEVAULT_OLLAMA_HOST", "http://127.0.0.1:1")
    from config import reset_config_cache

    reset_config_cache()
    import llm

    importlib.reload(llm)
    assert llm.is_model_available("llama3.2") is False
