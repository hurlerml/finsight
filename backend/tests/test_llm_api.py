import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import llm


class FakePullResponse:
    async def aiter_lines(self):
        yield json.dumps({"status": "pulling manifest"})
        yield json.dumps({"status": "pulling layer", "total": 100, "completed": 75})
        yield json.dumps({"status": "success"})

    def raise_for_status(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


class FakePullClient:
    def __init__(self, **_kwargs):
        self.response = FakePullResponse()

    def build_request(self, method: str, url: str, json: dict):
        return method, url, json

    async def send(self, _request, *, stream: bool):
        assert stream is True
        return self.response

    async def aclose(self) -> None:
        return None


def test_model_name_validation() -> None:
    assert llm._model_name(" qwen3-embedding:4b ") == "qwen3-embedding:4b"
    with pytest.raises(HTTPException):
        llm._model_name("model name; invalid")


def test_chat_model_change_keeps_existing_categories(monkeypatch) -> None:
    settings = llm.get_settings()
    old_model = settings.ollama_model
    settings.ollama_model = "old-chat-model"
    invalidations: list[bool] = []
    embedding_backfills: list[bytes] = []
    monkeypatch.setattr(llm, "update_model_preferences", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        llm,
        "invalidate_classification_context",
        lambda: invalidations.append(True),
    )
    monkeypatch.setattr(
        llm,
        "schedule_transaction_embedding_backfill",
        lambda dek: embedding_backfills.append(dek),
    )

    try:
        result = llm._activate_model(
            object(),  # type: ignore[arg-type]
            b"dek",
            model="new-chat-model",
            kind="chat",
        )
    finally:
        settings.ollama_model = old_model

    assert result["changed"] is True
    assert result["reset_count"] == 0
    assert result["queued_for_agent"] == 0
    assert invalidations == [True]
    assert embedding_backfills == []


def test_embedding_model_change_starts_full_rebuild(monkeypatch) -> None:
    settings = llm.get_settings()
    old_model = settings.ollama_embedding_model
    settings.ollama_embedding_model = "old-embedding-model"
    embedding_backfills: list[bytes] = []
    monkeypatch.setattr(llm, "update_model_preferences", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        llm,
        "schedule_transaction_embedding_backfill",
        lambda dek: embedding_backfills.append(dek),
    )

    try:
        result = llm._activate_model(
            object(),  # type: ignore[arg-type]
            b"dek",
            model="new-embedding-model",
            kind="embedding",
        )
    finally:
        settings.ollama_embedding_model = old_model

    assert result["changed"] is True
    assert result["rebuild_started"] is True
    assert embedding_backfills == [b"dek"]


def test_categorization_web_search_preference_is_persisted(monkeypatch) -> None:
    captured: list[bool] = []

    def update(_session, _dek, *, categorization_web_search_enabled=None, **_kwargs):
        captured.append(categorization_web_search_enabled)
        return SimpleNamespace(
            categorization_web_search_enabled=categorization_web_search_enabled
        )

    monkeypatch.setattr(llm, "update_model_preferences", update)

    result = llm.set_categorization_web_search(
        llm.CategorizationWebSearchPreference(enabled=False),
        session=object(),  # type: ignore[arg-type]
        dek=b"dek",
    )

    assert result == {"categorization_web_search_enabled": False}
    assert captured == [False]


def test_initial_model_setup_stores_model_and_starts_installer(monkeypatch) -> None:
    models: list[str] = []
    requests: list[bool] = []

    monkeypatch.setattr(
        llm,
        "update_model_preferences",
        lambda *_args, chat_model=None, **_kwargs: models.append(chat_model),
    )
    monkeypatch.setattr(
        llm,
        "request_model_setup",
        lambda: requests.append(True),
    )

    result = llm.configure_initial_models(
        llm.InitialModelSetupRequest(model="qwen3:8b"),
        session=object(),  # type: ignore[arg-type]
        dek=b"dek",
    )

    assert result == {"model": "qwen3:8b", "status": "queued"}
    assert models == ["qwen3:8b"]
    assert requests == [True]


def test_pull_stream_selects_downloaded_embedding_model(monkeypatch) -> None:
    settings = llm.get_settings()
    old_base_url = settings.ollama_base_url
    old_model = settings.ollama_embedding_model
    settings.ollama_base_url = "http://ollama.test"
    monkeypatch.setattr(llm.httpx, "AsyncClient", FakePullClient)

    async def run_pull():
        response = await llm.pull_model(
            llm.ModelPullRequest(model="qwen3-embedding:4b", kind="embedding")
        )
        return [json.loads(chunk) async for chunk in response.body_iterator]

    try:
        events = asyncio.run(run_pull())
    finally:
        settings.ollama_base_url = old_base_url
        settings.ollama_embedding_model = old_model

    assert events[-1] == {
        "status": "selected",
        "model": "qwen3-embedding:4b",
        "kind": "embedding",
    }
    assert events[1]["completed"] == 75
