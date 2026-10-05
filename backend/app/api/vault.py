from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlmodel import Session

from app.db import get_session
from app.schemas.vault import (
    PrivateEncryptionAudit,
    PrivateEncryptionStatus,
    VaultPasswordRequest,
    VaultRecoverRequest,
    VaultRecoveryConfirmRequest,
    VaultRecoveryPhraseResponse,
    VaultSetupResponse,
    VaultStatus,
    VaultUnlockResponse,
)
from app.deps import require_unlocked
from app.services import vault as vault_service
from app.services.vault import (
    InvalidMasterPasswordError,
    InvalidRecoveryPhraseError,
    VaultAlreadyInitializedError,
    VaultError,
    VaultNotInitializedError,
)
from app.services.vault_session import vault_session
from app.services.secure_repository import audit_private_payloads, private_payload_status

router = APIRouter(prefix="/api/vault", tags=["vault"])


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


@router.get("/status", response_model=VaultStatus)
def vault_status(
    session: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> VaultStatus:
    token = _bearer(authorization)
    # "unlocked" means THIS client session can decrypt — not merely that the process holds a DEK
    session_unlocked = vault_session.get_dek(token) is not None if token else False
    status = vault_service.get_status(session)
    return VaultStatus(
        initialized=status["initialized"],
        unlocked=session_unlocked,
        recovery_configured=status["recovery_configured"],
        recovery_confirmed=status["recovery_confirmed"],
    )


@router.post("/setup", response_model=VaultSetupResponse)
def vault_setup(
    body: VaultPasswordRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> VaultSetupResponse:
    try:
        token, recovery_phrase = vault_service.setup_vault(session, body.password)
    except VaultAlreadyInitializedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except VaultError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return VaultSetupResponse(
        token=token,
        message="Vault initialized; confirm the recovery phrase to continue",
        recovery_phrase=recovery_phrase,
    )


@router.post("/unlock", response_model=VaultUnlockResponse)
def vault_unlock(
    body: VaultPasswordRequest, session: Session = Depends(get_session)
) -> VaultUnlockResponse:
    try:
        token = vault_service.unlock_vault(session, body.password)
    except VaultNotInitializedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidMasterPasswordError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return VaultUnlockResponse(token=token, message="Vault unlocked")


@router.post("/recover", response_model=VaultUnlockResponse)
def vault_recover(
    body: VaultRecoverRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> VaultUnlockResponse:
    try:
        token = vault_service.recover_vault(
            session, body.recovery_phrase, body.new_password
        )
    except VaultNotInitializedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidRecoveryPhraseError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except VaultError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return VaultUnlockResponse(token=token, message="Master password reset and vault unlocked")


@router.post("/recovery/confirm", response_model=VaultStatus)
def recovery_confirm(
    body: VaultRecoveryConfirmRequest,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> VaultStatus:
    try:
        vault_service.confirm_recovery_phrase(
            session, body.recovery_phrase, dek, replace=body.replace
        )
    except (InvalidRecoveryPhraseError, VaultNotInitializedError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return VaultStatus(**vault_service.get_status(session))


@router.post("/recovery/regenerate", response_model=VaultRecoveryPhraseResponse)
def recovery_regenerate(
    response: Response,
    _dek: bytes = Depends(require_unlocked),
) -> VaultRecoveryPhraseResponse:
    phrase = vault_service.generate_replacement_recovery_phrase()
    response.headers["Cache-Control"] = "no-store"
    return VaultRecoveryPhraseResponse(recovery_phrase=phrase)


@router.post("/lock", response_model=VaultStatus)
def vault_lock(
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
) -> VaultStatus:
    vault_service.lock_vault()
    return VaultStatus(**vault_service.get_status(session))


@router.get("/encryption-status", response_model=PrivateEncryptionStatus)
def encryption_status(
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
) -> PrivateEncryptionStatus:
    return PrivateEncryptionStatus(**private_payload_status(session))


@router.get("/encryption-audit", response_model=PrivateEncryptionAudit)
def encryption_audit(
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> PrivateEncryptionAudit:
    return PrivateEncryptionAudit(**audit_private_payloads(session, dek))
