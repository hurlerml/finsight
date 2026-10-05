"""Local Ollama model discovery, installation, and selection."""

from __future__ import annotations

import json
import re
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.config import get_settings
from app.db import engine, get_session
from app.deps import require_unlocked
from app.services.embeddings import schedule_transaction_embedding_backfill
from app.services.llm_categorize import invalidate_classification_context
from app.services.ollama_setup import request_model_setup, setup_status
from app.services.secure_settings import update_model_preferences
from app.services.vault_session import vault_session

router = APIRouter(prefix="/api/llm", tags=["llm"])


class ModelSelection(BaseModel):
    model: str


class CategorizationWebSearchPreference(BaseModel):
    enabled: bool


class ModelPullRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    kind: Literal["chat", "embedding"]


class InitialModelSetupRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)


_MODEL_NAME = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?$"
)


def _model_name(value: str) -> str:
    model = value.strip()
    if not _MODEL_NAME.fullmatch(model):
        raise HTTPException(status_code=400, detail="Invalid Ollama model name")
    return model


def _activate_model(
    session: Session,
    dek: bytes,
    *,
    model: str,
    kind: Literal["chat", "embedding"],
) -> dict[str, object]:
    settings = get_settings()
    if kind == "embedding":
        changed = settings.ollama_embedding_model != model
        update_model_preferences(session, dek, embedding_model=model)
        rebuild_started = changed
        if rebuild_started:
            # A running backfill coalesces this request and performs another pass
            # with the newly selected model before it stops.
            schedule_transaction_embedding_backfill(dek)
        return {
            "active": model,
            "changed": changed,
            "rebuild_started": rebuild_started,
        }

    changed = settings.ollama_model != model
    update_model_preferences(session, dek, chat_model=model)
    if changed:
        invalidate_classification_context()
    return {
        "active": model,
        "changed": changed,
        "reset_count": 0,
        "rules_applied": 0,
        "queued_for_agent": 0,
    }


@router.get("/models")
def models() -> dict:
    settings = get_settings()
    if not settings.ollama_base_url.strip():
        return {"reachable": False, "active": settings.ollama_model, "models": [], "embedding_active": settings.ollama_embedding_model, "embedding_models": [], "auto_install": setup_status()}
    try:
        with httpx.Client(timeout=5) as client:
            payload = client.get(settings.ollama_base_url.rstrip("/") + "/api/tags").raise_for_status().json()
        entries = [item for item in payload.get("models", []) if item.get("name")]
        embedding_names = [
            str(item["name"])
            for item in entries
            if "embedding" in (item.get("capabilities") or [])
            or str(item["name"]) == settings.ollama_embedding_model
            or "embed" in str(item["name"]).lower()
        ]
        names = [str(item["name"]) for item in entries if str(item["name"]) not in embedding_names]
        return {"reachable": True, "active": settings.ollama_model, "models": names, "embedding_active": settings.ollama_embedding_model, "embedding_models": embedding_names, "auto_install": setup_status()}
    except (httpx.HTTPError, ValueError):
        return {"reachable": False, "active": settings.ollama_model, "models": [], "embedding_active": settings.ollama_embedding_model, "embedding_models": [], "auto_install": setup_status()}


@router.get("/preferences")
def preferences() -> dict[str, bool]:
    return {
        "categorization_web_search_enabled": (
            get_settings().categorization_web_search_enabled
        )
    }


@router.put("/preferences/categorization-web-search")
def set_categorization_web_search(
    preference: CategorizationWebSearchPreference,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> dict[str, bool]:
    stored = update_model_preferences(
        session,
        dek,
        categorization_web_search_enabled=preference.enabled,
    )
    return {
        "categorization_web_search_enabled": (
            stored.categorization_web_search_enabled
        )
    }


@router.post("/model")
def select_model(
    selection: ModelSelection,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> dict[str, object]:
    available = models()["models"]
    if selection.model not in available:
        raise HTTPException(status_code=400, detail="Model is not installed in Ollama")
    return _activate_model(
        session,
        dek,
        model=selection.model,
        kind="chat",
    )


@router.post("/models/setup")
def configure_initial_models(
    body: InitialModelSetupRequest,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> dict[str, str]:
    """Store the first-run chat model and start installing configured models."""
    model = _model_name(body.model)
    update_model_preferences(session, dek, chat_model=model)
    request_model_setup()
    return {"model": model, "status": "queued"}


@router.post("/embedding-model")
def select_embedding_model(
    selection: ModelSelection,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> dict[str, object]:
    available = models()["embedding_models"]
    if selection.model not in available:
        raise HTTPException(status_code=400, detail="Embedding model is not installed in Ollama")
    return _activate_model(
        session,
        dek,
        model=selection.model,
        kind="embedding",
    )


@router.post("/models/pull")
async def pull_model(body: ModelPullRequest) -> StreamingResponse:
    """Proxy Ollama's NDJSON pull progress and select the downloaded model."""
    settings = get_settings()
    base_url = settings.ollama_base_url.strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=503, detail="Ollama is not configured")

    model = _model_name(body.model)
    client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=5.0))
    try:
        request = client.build_request(
            "POST",
            f"{base_url}/api/pull",
            json={"model": model, "stream": True},
        )
        response = await client.send(request, stream=True)
        response.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        await client.aclose()
        raise HTTPException(
            status_code=502,
            detail=f"Could not start Ollama model download: {exc}",
        ) from exc

    async def progress():
        succeeded = False
        try:
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {"status": line}
                if event.get("error"):
                    yield json.dumps({"error": str(event["error"])}) + "\n"
                    return
                succeeded = succeeded or event.get("status") == "success"
                yield json.dumps(
                    {
                        key: event[key]
                        for key in ("status", "digest", "total", "completed")
                        if key in event
                    }
                ) + "\n"
        except httpx.HTTPError as exc:
            yield json.dumps({"error": f"Ollama download failed: {exc}"}) + "\n"
        finally:
            await response.aclose()
            await client.aclose()

        if succeeded:
            dek = vault_session.get_dek()
            if dek is None:
                if body.kind == "embedding":
                    settings.ollama_embedding_model = model
                else:
                    settings.ollama_model = model
            else:
                with Session(engine) as session:
                    _activate_model(
                        session,
                        dek,
                        model=model,
                        kind=body.kind,
                    )
            yield json.dumps(
                {"status": "selected", "model": model, "kind": body.kind}
            ) + "\n"

    return StreamingResponse(progress(), media_type="application/x-ndjson")
