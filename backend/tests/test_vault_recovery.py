from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.vault import VaultMeta
from app.services import crypto
from app.services import vault as vault_service
from app.services.vault_session import vault_session


@pytest.fixture
def vault_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[VaultMeta.__table__])
    monkeypatch.setattr(
        vault_service,
        "_backfill_and_verify_private_data",
        lambda *_, **__: None,
    )
    vault_session.lock()
    with Session(engine) as session:
        yield session
    vault_session.lock()


def test_recovery_phrase_rewraps_the_same_dek(vault_db: Session) -> None:
    setup_token, phrase = vault_service.setup_vault(vault_db, "original-password")
    assert len(phrase.split()) == 12
    assert crypto.recovery_entropy(phrase)

    original_dek = vault_service.require_dek(setup_token)
    meta = vault_db.get(VaultMeta, 1)
    assert meta is not None
    assert meta.recovery_salt is not None
    assert meta.recovery_wrapped_dek is not None
    assert phrase.encode() not in meta.recovery_wrapped_dek
    assert all(word.encode() not in meta.recovery_wrapped_dek for word in phrase.split())

    vault_service.confirm_recovery_phrase(vault_db, phrase, original_dek)
    vault_db.refresh(meta)
    assert meta.recovery_confirmed_at is not None

    vault_session.lock()
    recovered_token = vault_service.recover_vault(
        vault_db, phrase, "replacement-password"
    )
    assert vault_service.require_dek(recovered_token) == original_dek

    vault_session.lock()
    with pytest.raises(vault_service.InvalidMasterPasswordError):
        vault_service.unlock_vault(vault_db, "original-password")
    new_token = vault_service.unlock_vault(vault_db, "replacement-password")
    assert vault_service.require_dek(new_token) == original_dek


def test_new_vault_explicitly_initializes_first_run_state(
    vault_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    new_vault_flags: list[bool] = []

    def record_backfill(
        _session: Session,
        _dek: bytes,
        *,
        new_vault: bool = False,
    ) -> None:
        new_vault_flags.append(new_vault)

    monkeypatch.setattr(
        vault_service,
        "_backfill_and_verify_private_data",
        record_backfill,
    )

    vault_service.setup_vault(vault_db, "original-password")

    assert new_vault_flags == [True]


def test_failed_initial_audit_does_not_leave_initialized_vault(
    vault_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_backfill(*_args, **_kwargs) -> None:
        raise RuntimeError("audit failed")

    monkeypatch.setattr(
        vault_service,
        "_backfill_and_verify_private_data",
        fail_backfill,
    )

    with pytest.raises(vault_service.VaultError):
        vault_service.setup_vault(vault_db, "original-password")

    assert vault_service.is_initialized(vault_db) is False


def test_lock_endpoint_requires_authentication() -> None:
    from app.main import PUBLIC_PATHS

    assert "/api/vault/lock" not in PUBLIC_PATHS


def test_invalid_recovery_phrase_cannot_reset_password(vault_db: Session) -> None:
    _token, _phrase = vault_service.setup_vault(vault_db, "original-password")
    invalid_phrase = "abandon " * 11 + "ability"

    with pytest.raises(vault_service.InvalidRecoveryPhraseError):
        vault_service.recover_vault(vault_db, invalid_phrase, "replacement-password")

    vault_session.lock()
    vault_service.unlock_vault(vault_db, "original-password")


def test_replacing_recovery_invalidates_old_phrase(vault_db: Session) -> None:
    token, old_phrase = vault_service.setup_vault(vault_db, "original-password")
    dek = vault_service.require_dek(token)

    new_phrase = vault_service.generate_replacement_recovery_phrase()
    assert new_phrase != old_phrase
    vault_service.confirm_recovery_phrase(vault_db, old_phrase, dek)

    vault_service.confirm_recovery_phrase(vault_db, new_phrase, dek, replace=True)
    with pytest.raises(vault_service.InvalidRecoveryPhraseError):
        vault_service.confirm_recovery_phrase(vault_db, old_phrase, dek)

    vault_service.confirm_recovery_phrase(vault_db, new_phrase, dek)
    assert vault_service.get_status(vault_db)["recovery_confirmed"] is True
