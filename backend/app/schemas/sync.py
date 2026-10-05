from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import JobStatus, SyncStatus


class SyncRequest(BaseModel):
    account_id: int | None = None
    connection_id: int | None = None
    source: str | None = None
    # "sync" = smart refresh. "backfill" = force full history from history_from.
    mode: str = Field(default="sync", pattern="^(sync|backfill)$")
    history_from: date | None = None


class SyncSettingsUpdate(BaseModel):
    history_from: date | None = None


class SyncTriggerResponse(BaseModel):
    job_ids: list[int]
    message: str


class SyncStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: int
    account_name: str
    status: SyncStatus
    last_success_at: datetime | None
    last_error: str | None
    pending_jobs: int
    latest_job_status: JobStatus | None = None
    history_from: date | None = None
    backfill_cursor: date | None = None
    latest_booking_date: date | None = None
    earliest_booking_date: date | None = None


class SyncProgressRead(BaseModel):
    phase: str
    message: str | None = None
    awaiting_user_action: bool = False
    source: str | None = None


class ConnectionSyncStatusRead(BaseModel):
    connection_id: int
    pending_jobs: int
    running_jobs: int
    latest_job_status: JobStatus | None = None
    latest_job_error: str | None = None
