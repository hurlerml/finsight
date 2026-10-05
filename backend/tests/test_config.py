from app.config import Settings


def test_model_defaults_can_be_configured_through_environment(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_MODEL", "environment-chat-model")
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "environment-embedding-model")
    monkeypatch.setenv("OLLAMA_AUTO_PULL", "false")

    settings = Settings(_env_file=None)

    assert settings.ollama_model == "environment-chat-model"
    assert settings.ollama_embedding_model == "environment-embedding-model"
    assert not hasattr(settings, "ollama_auto_pull")


def test_model_selection_remains_mutable_runtime_state() -> None:
    settings = Settings(_env_file=None)

    settings.ollama_model = "custom-chat-model"
    settings.ollama_embedding_model = "custom-embedding-model"

    assert settings.ollama_model == "custom-chat-model"
    assert settings.ollama_embedding_model == "custom-embedding-model"
