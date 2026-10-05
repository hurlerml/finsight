"""Ciphertext-first views for sync and background-job runtime metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import insert, update
from sqlmodel import Session, select

from app.models.enums import JobStatus, JobType, SyncStatus
from app.models.job import Job
from app.models.sync_state import SyncState
from app.services.secure_data import ENCRYPTION_VERSION, encrypt_payload
from app.services.secure_repository import decrypted_financial_payload

_UNSET = object()


def _date(value: object) -> date | None:
    return date.fromisoformat(str(value)) if value is not None else None


def _datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None


@dataclass(frozen=True)
class JobPrivateData:
    payload: dict[str, Any]
    error: str | None


@dataclass(frozen=True)
class SyncStatePrivateData:
    cursor: str | None
    history_from: date | None
    backfill_cursor: date | None
    window_start: datetime | None
    last_success_at: datetime | None
    last_error: str | None


def decode_job(row: Job, dek: bytes) -> JobPrivateData:
    payload = decrypted_financial_payload(row, dek)
    private_payload = payload.get("payload")
    return JobPrivateData(
        payload=private_payload if isinstance(private_payload, dict) else {},
        error=str(payload["error"]) if payload.get("error") is not None else None,
    )


def decode_sync_state(row: SyncState, dek: bytes) -> SyncStatePrivateData:
    payload = decrypted_financial_payload(row, dek)
    return SyncStatePrivateData(
        cursor=str(payload["cursor"]) if payload.get("cursor") is not None else None,
        history_from=_date(payload.get("history_from")),
        backfill_cursor=_date(payload.get("backfill_cursor")),
        window_start=_datetime(payload.get("window_start")),
        last_success_at=_datetime(payload.get("last_success_at")),
        last_error=str(payload["last_error"]) if payload.get("last_error") is not None else None,
    )


def insert_job_payload(
    session: Session,
    dek: bytes,
    *,
    job_type: JobType,
    status: JobStatus = JobStatus.PENDING,
    payload: dict[str, Any] | None = None,
    max_attempts: int = 5,
) -> Job:
    job_id = session.execute(
        insert(Job)
        .values(
            job_type=job_type,
            status=status,
            attempts=0,
            max_attempts=max_attempts,
        )
        .returning(Job.id)
    ).scalar_one()
    session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(
            encrypted_payload=encrypt_payload(
                dek,
                domain="job",
                record_id=job_id,
                payload={"payload": payload, "error": None},
            ),
            encryption_version=ENCRYPTION_VERSION,
        )
    )
    session.flush()
    row = session.get(Job, job_id)
    if row is None:
        raise RuntimeError("Ciphertext job insert failed")
    return row


def update_job_payload(
    session: Session,
    row: Job,
    dek: bytes,
    *,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    if row.id is None:
        raise ValueError("Persisted job is missing its id")
    current = decode_job(row, dek)
    private_payload = current.payload if payload is None else payload
    session.execute(
        update(Job)
        .where(Job.id == row.id)
        .values(
            encrypted_payload=encrypt_payload(
                dek,
                domain="job",
                record_id=row.id,
                payload={"payload": private_payload, "error": error},
            ),
            encryption_version=ENCRYPTION_VERSION,
        )
    )
    session.flush()
    session.expire(row)


def insert_sync_state_payload(
    session: Session,
    dek: bytes,
    *,
    account_id: int,
    history_from: date | None = None,
    status: SyncStatus = SyncStatus.IDLE,
) -> SyncState:
    state_id = session.execute(
        insert(SyncState)
        .values(account_id=account_id, status=status)
        .returning(SyncState.id)
    ).scalar_one()
    payload = {
        "cursor": None,
        "history_from": history_from,
        "backfill_cursor": None,
        "window_start": None,
        "last_success_at": None,
        "last_error": None,
    }
    session.execute(
        update(SyncState)
        .where(SyncState.id == state_id)
        .values(
            encrypted_payload=encrypt_payload(
                dek, domain="sync-state", record_id=state_id, payload=payload
            ),
            encryption_version=ENCRYPTION_VERSION,
        )
    )
    session.flush()
    row = session.get(SyncState, state_id)
    if row is None:
        raise RuntimeError("Ciphertext sync state insert failed")
    return row


def update_sync_state_payload(
    session: Session,
    row: SyncState,
    dek: bytes,
    **changes: object,
) -> SyncStatePrivateData:
    """Update sync-state ciphertext. Public status may be passed as status=."""
    if row.id is None:
        raise ValueError("Persisted sync state is missing its id")
    payload = decrypted_financial_payload(row, dek)
    status = changes.pop("status", _UNSET)
    for key, value in changes.items():
        payload[key] = value.value if hasattr(value, "value") else value
    values: dict[str, object] = {
        "encrypted_payload": encrypt_payload(
            dek, domain="sync-state", record_id=row.id, payload=payload
        ),
        "encryption_version": ENCRYPTION_VERSION,
    }
    if status is not _UNSET:
        values["status"] = status
    session.execute(update(SyncState).where(SyncState.id == row.id).values(**values))
    session.flush()
    session.expire(row)
    return decode_sync_state(row, dek)


def get_or_create_sync_state(
    session: Session,
    dek: bytes,
    account_id: int,
    *,
    history_from: date | None = None,
) -> SyncState:
    state = session.exec(
        select(SyncState).where(SyncState.account_id == account_id)
    ).first()
    if state:
        return state
    return insert_sync_state_payload(
        session, dek, account_id=account_id, history_from=history_from
    )
