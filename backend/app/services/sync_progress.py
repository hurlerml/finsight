"""Process-local sync progress for UI polling (FinTS SCA wait, etc.)."""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class SyncProgress:
    phase: str = "idle"  # idle | running | awaiting_user_action | error
    message: str | None = None
    awaiting_user_action: bool = False
    source: str | None = None


_lock = threading.Lock()
_progress = SyncProgress()


def get_sync_progress() -> SyncProgress:
    with _lock:
        return SyncProgress(
            phase=_progress.phase,
            message=_progress.message,
            awaiting_user_action=_progress.awaiting_user_action,
            source=_progress.source,
        )


def set_sync_progress(
    *,
    phase: str,
    message: str | None = None,
    awaiting_user_action: bool = False,
    source: str | None = None,
) -> None:
    with _lock:
        _progress.phase = phase
        _progress.message = message
        _progress.awaiting_user_action = awaiting_user_action
        _progress.source = source


def clear_sync_progress() -> None:
    set_sync_progress(phase="idle", message=None, awaiting_user_action=False, source=None)
