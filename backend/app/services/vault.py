"""Vault setup/unlock and connection secret encrypt/decrypt."""

from __future__ import annotations

import hmac
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, select

from app.models.vault import Connection, VaultMeta
from app.services import crypto
from app.services.vault_session import vault_session

if TYPE_CHECKING:
    from app.services.secure_settings import ModelPreferences


class VaultError(Exception):
    pass


class VaultLockedError(VaultError):
    pass


class VaultNotInitializedError(VaultError):
    pass


class VaultAlreadyInitializedError(VaultError):
    pass


class InvalidMasterPasswordError(VaultError):
    pass


class InvalidRecoveryPhraseError(VaultError):
    pass


def _backfill_and_verify_private_data(
    session: Session,
    dek: bytes,
    *,
    new_vault: bool = False,
) -> "ModelPreferences":
    from app.services.secure_repository import audit_private_payloads
    from app.services.secure_settings import (
        ensure_app_settings,
        update_model_preferences,
    )
    from app.services.seed import seed_categories
    from app.services.sync import backfill_fints_card_titles

    seed_categories(session, dek, commit=False)
    preferences = ensure_app_settings(session, dek, commit=False)
    if new_vault:
        # A newly created vault must always enter first-run onboarding. Do not
        # infer this solely from whether an app-settings row already exists.
        preferences = update_model_preferences(
            session,
            dek,
            onboarding_completed=False,
            commit=False,
        )
    # Persist titles for older FinTS card rows as part of the
    # normal unlock verification, so no extra sync is required after upgrade.
    backfill_fints_card_titles(session, dek, commit=False)
    audit = audit_private_payloads(session, dek)
    failed = {
        name: counts
        for name, counts in audit.items()
        if counts["pending"] or counts["unreadable"]
    }
    if failed:
        raise VaultError(f"Private data encryption verification failed: {failed}")
    return preferences


def is_initialized(session: Session) -> bool:
    return session.get(VaultMeta, 1) is not None


def get_status(session: Session) -> dict[str, bool]:
    meta = session.get(VaultMeta, 1)
    return {
        "initialized": meta is not None,
        "unlocked": vault_session.is_unlocked(),
        "recovery_configured": bool(meta and meta.recovery_wrapped_dek),
        "recovery_confirmed": bool(meta and meta.recovery_confirmed_at),
    }


def setup_vault(session: Session, password: str) -> tuple[str, str]:
    if is_initialized(session):
        raise VaultAlreadyInitializedError("Vault already initialized")
    if len(password) < 8:
        raise VaultError("Master password must be at least 8 characters")

    salt = crypto.new_salt()
    dek = crypto.new_dek()
    wrapped = crypto.wrap_dek(password, salt, dek)
    recovery_phrase = crypto.generate_recovery_phrase()
    recovery_salt = crypto.new_salt()
    recovery_wrapped = crypto.wrap_dek_with_recovery_phrase(
        recovery_phrase, recovery_salt, dek
    )
    meta = VaultMeta(
        id=1,
        salt=salt,
        wrapped_dek=wrapped,
        recovery_salt=recovery_salt,
        recovery_wrapped_dek=recovery_wrapped,
        recovery_version=1,
    )
    session.add(meta)
    try:
        session.flush()
        _backfill_and_verify_private_data(session, dek, new_vault=True)
        session.commit()
    except Exception as exc:
        session.rollback()
        vault_session.lock()
        raise VaultError("Private data encryption verification failed") from exc
    return vault_session.unlock(dek), recovery_phrase


def unlock_vault(session: Session, password: str) -> str:
    meta = session.get(VaultMeta, 1)
    if meta is None:
        raise VaultNotInitializedError("Vault not initialized")
    try:
        dek = crypto.unwrap_dek(password, meta.salt, meta.wrapped_dek)
    except Exception as exc:
        raise InvalidMasterPasswordError("Invalid master password") from exc
    try:
        preferences = _backfill_and_verify_private_data(session, dek)
        session.commit()
    except Exception as exc:
        session.rollback()
        vault_session.lock()
        raise VaultError("Private data encryption verification failed") from exc
    if getattr(preferences, "onboarding_completed", False):
        from app.services.ollama_setup import request_model_setup

        request_model_setup()
    return vault_session.unlock(dek)


def _unwrap_recovery_dek(meta: VaultMeta, phrase: str) -> bytes:
    if (
        meta.recovery_version != 1
        or not meta.recovery_salt
        or not meta.recovery_wrapped_dek
    ):
        raise InvalidRecoveryPhraseError("Vault recovery is not configured")
    try:
        return crypto.unwrap_dek_with_recovery_phrase(
            phrase, meta.recovery_salt, meta.recovery_wrapped_dek
        )
    except Exception as exc:
        raise InvalidRecoveryPhraseError("Invalid recovery phrase") from exc


def confirm_recovery_phrase(
    session: Session, phrase: str, dek: bytes, *, replace: bool = False
) -> None:
    meta = session.get(VaultMeta, 1)
    if meta is None:
        raise VaultNotInitializedError("Vault not initialized")

    if replace:
        try:
            recovery_salt = crypto.new_salt()
            wrapped_dek = crypto.wrap_dek_with_recovery_phrase(
                phrase, recovery_salt, dek
            )
        except Exception as exc:
            raise InvalidRecoveryPhraseError("Invalid recovery phrase") from exc
        meta.recovery_salt = recovery_salt
        meta.recovery_wrapped_dek = wrapped_dek
        meta.recovery_version = 1
    else:
        recovered_dek = _unwrap_recovery_dek(meta, phrase)
        if not hmac.compare_digest(recovered_dek, dek):
            raise InvalidRecoveryPhraseError("Invalid recovery phrase")
    meta.recovery_confirmed_at = datetime.now(timezone.utc)
    session.add(meta)
    session.commit()


def generate_replacement_recovery_phrase() -> str:
    """Generate a candidate; the active wrapper changes only after confirmation."""
    return crypto.generate_recovery_phrase()


def recover_vault(session: Session, phrase: str, new_password: str) -> str:
    if len(new_password) < 8:
        raise VaultError("Master password must be at least 8 characters")
    meta = session.get(VaultMeta, 1)
    if meta is None:
        raise VaultNotInitializedError("Vault not initialized")

    dek = _unwrap_recovery_dek(meta, phrase)
    try:
        preferences = _backfill_and_verify_private_data(session, dek)
    except Exception as exc:
        session.rollback()
        vault_session.lock()
        raise VaultError("Private data encryption verification failed") from exc

    salt = crypto.new_salt()
    meta.salt = salt
    meta.wrapped_dek = crypto.wrap_dek(new_password, salt, dek)
    session.add(meta)
    session.commit()
    if getattr(preferences, "onboarding_completed", False):
        from app.services.ollama_setup import request_model_setup

        request_model_setup()
    return vault_session.unlock(dek)


def lock_vault() -> None:
    vault_session.lock()


def require_dek(token: str | None = None) -> bytes:
    dek = vault_session.get_dek(token)
    if dek is None:
        raise VaultLockedError("Vault is locked")
    return dek


def encrypt_secrets(dek: bytes, secrets: dict[str, Any]) -> bytes:
    return crypto.encrypt(dek, json.dumps(secrets).encode("utf-8"))


def decrypt_secrets(dek: bytes, blob: bytes) -> dict[str, Any]:
    raw = crypto.decrypt(dek, blob)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise VaultError("Invalid secrets payload")
    return data


def list_connection_secrets(session: Session, dek: bytes) -> list[tuple[Connection, dict[str, Any]]]:
    rows = session.exec(select(Connection)).all()
    out: list[tuple[Connection, dict[str, Any]]] = []
    for row in rows:
        out.append((row, decrypt_secrets(dek, row.secrets_encrypted)))
    return out
