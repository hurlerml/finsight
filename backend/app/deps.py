"""FastAPI dependencies for vault session auth."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.services.vault import VaultLockedError, require_dek
from app.services.vault_session import vault_session


def _extract_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def require_unlocked(
    authorization: str | None = Header(default=None),
) -> bytes:
    token = _extract_token(authorization)
    try:
        return require_dek(token)
    except VaultLockedError as exc:
        raise HTTPException(status_code=401, detail="Vault is locked") from exc


def optional_unlocked(
    authorization: str | None = Header(default=None),
) -> bytes | None:
    token = _extract_token(authorization)
    if not token:
        return None
    return vault_session.get_dek(token)


def get_db_session() -> Session:  # pragma: no cover - alias for clarity
    raise RuntimeError("Use Depends(get_session)")


# Re-export for routers
SessionDep = Depends(get_session)
UnlockedDep = Depends(require_unlocked)
