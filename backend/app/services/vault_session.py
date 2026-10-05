"""In-memory vault session: DEK lives only in process RAM after unlock."""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class VaultSessionState:
    token: str
    dek: bytes
    unlocked_at: datetime
    last_active: datetime


class VaultSessionStore:
    """Single-user session store for the local vault."""

    def __init__(self, idle_timeout_minutes: int | None = None) -> None:
        if idle_timeout_minutes is None:
            try:
                from app.config import get_settings

                idle_timeout_minutes = get_settings().vault_idle_timeout_minutes
            except Exception:
                idle_timeout_minutes = 60
        self._lock = threading.Lock()
        self._state: VaultSessionState | None = None
        self._idle_timeout = timedelta(minutes=idle_timeout_minutes)

    def unlock(self, dek: bytes) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        with self._lock:
            self._state = VaultSessionState(
                token=token, dek=dek, unlocked_at=now, last_active=now
            )
        return token

    def lock(self) -> None:
        with self._lock:
            self._state = None

    def is_unlocked(self) -> bool:
        with self._lock:
            return self._get_valid_state_unlocked() is not None

    def get_dek(self, token: str | None = None) -> bytes | None:
        with self._lock:
            state = self._get_valid_state_unlocked()
            if state is None:
                return None
            if token is not None and not secrets.compare_digest(state.token, token):
                return None
            state.last_active = datetime.now(timezone.utc)
            return state.dek

    def touch(self, token: str) -> bool:
        return self.get_dek(token) is not None

    def _get_valid_state_unlocked(self) -> VaultSessionState | None:
        state = self._state
        if state is None:
            return None
        if datetime.now(timezone.utc) - state.last_active > self._idle_timeout:
            self._state = None
            return None
        return state


vault_session = VaultSessionStore()
