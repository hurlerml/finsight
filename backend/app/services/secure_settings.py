"""Encrypted application preferences that survive backend restarts."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import insert, update
from sqlmodel import Session

from app.config import get_settings
from app.models.app_setting import AppSetting
from app.services.secure_data import ENCRYPTION_VERSION, encrypt_payload
from app.services.secure_repository import decrypted_financial_payload


@dataclass(frozen=True)
class ModelPreferences:
    chat_model: str
    embedding_model: str
    categorization_web_search_enabled: bool
    onboarding_completed: bool


def _payload() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "chat_model": settings.ollama_model,
        "embedding_model": settings.ollama_embedding_model,
        "categorization_web_search_enabled": (
            settings.categorization_web_search_enabled
        ),
        "onboarding_completed": False,
    }


def ensure_app_settings(
    session: Session,
    dek: bytes,
    *,
    commit: bool = True,
) -> ModelPreferences:
    row = session.get(AppSetting, 1)
    if row is None:
        session.execute(insert(AppSetting).values(id=1))
        session.execute(
            update(AppSetting)
            .where(AppSetting.id == 1)
            .values(
                encrypted_payload=encrypt_payload(
                    dek,
                    domain="app-setting",
                    record_id=1,
                    payload=_payload(),
                ),
                encryption_version=ENCRYPTION_VERSION,
            )
        )
        if commit:
            session.commit()
        else:
            session.flush()
        row = session.get(AppSetting, 1)
        if row is None:
            raise RuntimeError("Ciphertext application settings insert failed")

    stored = decrypted_financial_payload(row, dek)
    settings = get_settings()
    chat_model = str(stored.get("chat_model") or settings.ollama_model)
    embedding_model = str(
        stored.get("embedding_model") or settings.ollama_embedding_model
    )
    stored_web_search = stored.get("categorization_web_search_enabled")
    categorization_web_search_enabled = (
        settings.categorization_web_search_enabled
        if stored_web_search is None
        else stored_web_search is True
    )
    # Settings written before onboarding existed belong to an already-running
    # installation and must not suddenly redirect that user into first-run
    # setup. Newly created rows explicitly store False in _payload().
    stored_onboarding = stored.get("onboarding_completed")
    onboarding_completed = (
        True if stored_onboarding is None else stored_onboarding is True
    )
    settings.ollama_model = chat_model
    settings.ollama_embedding_model = embedding_model
    settings.categorization_web_search_enabled = (
        categorization_web_search_enabled
    )
    return ModelPreferences(
        chat_model=chat_model,
        embedding_model=embedding_model,
        categorization_web_search_enabled=categorization_web_search_enabled,
        onboarding_completed=onboarding_completed,
    )


def update_model_preferences(
    session: Session,
    dek: bytes,
    *,
    chat_model: str | None = None,
    embedding_model: str | None = None,
    categorization_web_search_enabled: bool | None = None,
    onboarding_completed: bool | None = None,
    commit: bool = True,
) -> ModelPreferences:
    current = ensure_app_settings(session, dek, commit=False)
    values = {
        "chat_model": current.chat_model if chat_model is None else chat_model,
        "embedding_model": (
            current.embedding_model if embedding_model is None else embedding_model
        ),
        "categorization_web_search_enabled": (
            current.categorization_web_search_enabled
            if categorization_web_search_enabled is None
            else categorization_web_search_enabled
        ),
        "onboarding_completed": (
            current.onboarding_completed
            if onboarding_completed is None
            else onboarding_completed
        ),
    }
    session.execute(
        update(AppSetting)
        .where(AppSetting.id == 1)
        .values(
            encrypted_payload=encrypt_payload(
                dek,
                domain="app-setting",
                record_id=1,
                payload=values,
            ),
            encryption_version=ENCRYPTION_VERSION,
        )
    )
    if commit:
        session.commit()
    else:
        session.flush()
    settings = get_settings()
    settings.ollama_model = values["chat_model"]
    settings.ollama_embedding_model = values["embedding_model"]
    settings.categorization_web_search_enabled = bool(
        values["categorization_web_search_enabled"]
    )
    return ModelPreferences(**values)
