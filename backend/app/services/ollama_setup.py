"""Install onboarding-selected Ollama models in the background."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import asdict, dataclass
from typing import Literal

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

SetupPhase = Literal[
    "disabled",
    "pending",
    "waiting",
    "checking",
    "downloading",
    "ready",
    "error",
]


@dataclass
class OllamaSetupStatus:
    enabled: bool = False
    phase: SetupPhase = "disabled"
    model: str | None = None
    completed: int = 0
    total: int = 0
    error: str | None = None


_status = OllamaSetupStatus()
_setup_request_lock = threading.Lock()
_setup_request_generation = 0


def setup_status() -> dict[str, object]:
    """Return a snapshot suitable for the model-settings API."""
    return asdict(_status)


def request_model_setup() -> None:
    """Ask the background installer to process the current configuration."""
    global _setup_request_generation
    with _setup_request_lock:
        _setup_request_generation += 1
    if _status.enabled and _status.phase in {"pending", "ready", "error"}:
        _set_status(
            phase="checking",
            model=None,
            completed=0,
            total=0,
            error=None,
        )


def _requested_generation() -> int:
    with _setup_request_lock:
        return _setup_request_generation


def _set_status(**changes: object) -> None:
    for key, value in changes.items():
        setattr(_status, key, value)


def _configured_models() -> list[str]:
    settings = get_settings()
    return list(
        dict.fromkeys(
            model.strip()
            for model in (
                settings.ollama_model,
                settings.ollama_embedding_model,
            )
            if model.strip()
        )
    )


async def _installed_models(client: httpx.AsyncClient, base_url: str) -> set[str]:
    response = await client.get(f"{base_url}/api/tags")
    response.raise_for_status()
    payload = response.json()
    return {
        str(item["name"])
        for item in payload.get("models", [])
        if item.get("name")
    }


async def _pull_model(
    client: httpx.AsyncClient,
    base_url: str,
    model: str,
) -> None:
    _set_status(
        phase="downloading",
        model=model,
        completed=0,
        total=0,
        error=None,
    )
    logger.info("Downloading configured Ollama model %s", model)
    last_reported_percent = -10
    async with client.stream(
        "POST",
        f"{base_url}/api/pull",
        json={"model": model, "stream": True},
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line:
                continue
            event = json.loads(line)
            if event.get("error"):
                raise RuntimeError(str(event["error"]))
            completed = int(event.get("completed") or 0)
            total = int(event.get("total") or 0)
            _set_status(completed=completed, total=total)
            if total > 0:
                percent = min(100, int((completed / total) * 100))
                if percent >= last_reported_percent + 10:
                    logger.info("Ollama model %s download: %d%%", model, percent)
                    last_reported_percent = percent
    logger.info("Configured Ollama model %s is installed", model)


async def ollama_model_setup_loop() -> None:
    """Install missing configured models whenever setup is requested."""
    settings = get_settings()
    base_url = settings.ollama_base_url.strip().rstrip("/")
    if not base_url:
        _set_status(enabled=False, phase="disabled")
        return

    _set_status(enabled=True, phase="pending", error=None)
    handled_generation = 0
    while True:
        while _requested_generation() <= handled_generation:
            await asyncio.sleep(0.5)

        request_generation = _requested_generation()
        logged_wait = False
        while True:
            # A newer request may have changed the configured model while the
            # previous attempt was waiting for Ollama.
            request_generation = max(request_generation, _requested_generation())
            try:
                timeout = httpx.Timeout(None, connect=5.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    _set_status(phase="checking", model=None, error=None)
                    installed = await _installed_models(client, base_url)
                    missing = [
                        model for model in _configured_models() if model not in installed
                    ]
                    for model in missing:
                        await _pull_model(client, base_url, model)

                _set_status(
                    phase="ready",
                    model=None,
                    completed=0,
                    total=0,
                    error=None,
                )
                handled_generation = request_generation
                break
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPStatusError, RuntimeError) as exc:
                status_code = (
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else 400
                )
                if status_code >= 500:
                    message = str(exc)
                    _set_status(phase="waiting", error=message)
                    if not logged_wait:
                        logger.warning(
                            "Waiting for Ollama before installing configured models: %s",
                            message,
                        )
                        logged_wait = True
                    await asyncio.sleep(15)
                    continue
                message = str(exc)
                _set_status(phase="error", error=message)
                logger.error("Automatic Ollama model installation failed: %s", message)
                handled_generation = request_generation
                break
            except (httpx.HTTPError, ValueError) as exc:
                message = str(exc)
                _set_status(phase="waiting", error=message)
                if not logged_wait:
                    logger.warning(
                        "Waiting for Ollama before installing configured models: %s",
                        message,
                    )
                    logged_wait = True
                await asyncio.sleep(15)
