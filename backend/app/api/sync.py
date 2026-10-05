from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.deps import require_unlocked
from app.models import Account, Connection, Job, SyncState
from app.models.enums import JobStatus, JobType, SyncStatus
from app.schemas.sync import (
    ConnectionSyncStatusRead,
    SyncProgressRead,
    SyncRequest,
    SyncSettingsUpdate,
    SyncStatusRead,
    SyncTriggerResponse,
)
from app.services.sync import (
    connection_sync_statuses,
    default_history_from,
    enqueue_sync,
    update_sync_settings,
)
from app.services.sync_progress import get_sync_progress
from app.services.secure_accounts import decode_account
from app.services.secure_runtime import decode_job, decode_sync_state
from app.services.secure_transactions import load_transactions

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.post("", response_model=SyncTriggerResponse)
def trigger_sync(
    body: SyncRequest | None = None,
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
) -> SyncTriggerResponse:
    body = body or SyncRequest()
    job_ids = enqueue_sync(
        session,
        account_id=body.account_id,
        connection_id=body.connection_id,
        source=body.source,
        mode=body.mode,
        history_from=body.history_from,
    )
    if body.mode == "backfill":
        message = "History load enqueued" if job_ids else "No enabled connections"
    else:
        message = "Refresh enqueued" if job_ids else "No enabled connections"
    return SyncTriggerResponse(job_ids=job_ids, message=message)


@router.get("/progress", response_model=SyncProgressRead)
def sync_progress(_dek: bytes = Depends(require_unlocked)) -> SyncProgressRead:
    st = get_sync_progress()
    return SyncProgressRead(
        phase=st.phase,
        message=st.message,
        awaiting_user_action=st.awaiting_user_action,
        source=st.source,
    )


@router.patch("/accounts/{account_id}/settings", response_model=SyncStatusRead)
def patch_sync_settings(
    account_id: int,
    body: SyncSettingsUpdate,
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
) -> SyncStatusRead:
    account = session.get(Account, account_id)
    if account is None or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")
    state = update_sync_settings(session, account_id, history_from=body.history_from)
    return _status_for_account(session, account, _dek, state)


@router.get("/connections/status", response_model=list[ConnectionSyncStatusRead])
def connection_sync_status(
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> list[ConnectionSyncStatusRead]:
    connection_ids = [
        int(value)
        for value in session.exec(select(Connection.id)).all()
        if value is not None
    ]
    summaries = connection_sync_statuses(session, dek, connection_ids)
    return [
        ConnectionSyncStatusRead(
            connection_id=connection_id,
            pending_jobs=summary.get("pending_jobs", 0),
            running_jobs=summary.get("running_jobs", 0),
            latest_job_status=summary.get("latest_job_status"),
            latest_job_error=summary.get("latest_job_error"),
        )
        for connection_id, summary in summaries.items()
    ]


@router.get("/status", response_model=list[SyncStatusRead])
def sync_status(
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
) -> list[SyncStatusRead]:
    accounts = session.exec(select(Account).where(Account.is_active == True)).all()  # noqa: E712
    return [_status_for_account(session, acc, _dek) for acc in accounts]


def _status_for_account(
    session: Session,
    acc: Account,
    dek: bytes,
    state: SyncState | None = None,
) -> SyncStatusRead:
    if state is None:
        state = session.exec(
            select(SyncState).where(SyncState.account_id == acc.id)
        ).first()
    # Job payloads are encrypted, so the target account cannot be filtered in
    # SQL. Decode sync jobs and scope them to this account/connection. A
    # pending sync for Binance must not make every other account look yellow.
    sync_jobs = session.exec(
        select(Job)
        .where(Job.job_type == JobType.SYNC)
        .order_by(Job.created_at.desc())
    ).all()
    targeted_jobs = [
        job for job in sync_jobs if _job_targets_account(job, acc, dek)
    ]
    pending = [
        job
        for job in targeted_jobs
        if job.status in (JobStatus.PENDING, JobStatus.RUNNING)
    ]
    latest_job = targeted_jobs[0] if targeted_jobs else None
    transactions = load_transactions(session, dek, account_id=acc.id)
    dates = [transaction.booking_date for transaction in transactions]
    latest_booking = max(dates) if dates else None
    earliest_booking = min(dates) if dates else None
    account = decode_account(acc, dek)
    private_state = decode_sync_state(state, dek) if state is not None else None
    return SyncStatusRead(
        account_id=acc.id,  # type: ignore[arg-type]
        account_name=account.name,
        status=state.status if state else SyncStatus.IDLE,
        last_success_at=private_state.last_success_at if private_state else None,
        last_error=private_state.last_error if private_state else None,
        pending_jobs=len(pending),
        latest_job_status=latest_job.status if latest_job else None,
        history_from=(
            private_state.history_from
            if private_state and private_state.history_from
            else default_history_from()
        ),
        backfill_cursor=private_state.backfill_cursor if private_state else None,
        latest_booking_date=latest_booking,
        earliest_booking_date=earliest_booking,
    )


def _job_targets_account(job: Job, account: Account, dek: bytes) -> bool:
    """Return whether an encrypted sync job applies to ``account``."""

    try:
        payload = decode_job(job, dek).payload
    except Exception:
        # An unreadable private payload must not leak a global busy state to
        # unrelated accounts. The worker will surface the actual job error.
        return False

    target_account_id = payload.get("account_id")
    if target_account_id is not None:
        try:
            return int(target_account_id) == int(account.id)
        except (TypeError, ValueError):
            return False

    target_connection_id = payload.get("connection_id")
    if target_connection_id is not None:
        try:
            return (
                account.connection_id is not None
                and int(target_connection_id) == int(account.connection_id)
            )
        except (TypeError, ValueError):
            return False

    target_source = payload.get("source")
    if target_source is not None:
        source_value = getattr(account.source, "value", account.source)
        return str(target_source) == str(source_value)

    # Kept for jobs created by older versions. New global refreshes are fanned
    # out into connection-scoped jobs before they enter the queue.
    return True
