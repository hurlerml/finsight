"""Background job worker polling the jobs table."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.config import get_settings
from app.db import engine
from app.models import Job
from app.models.enums import JobStatus, JobType
from app.services.categorize import apply_rules
from app.services.match import run_matching
from app.services.sync import run_sync_job
from app.services.sync_progress import clear_sync_progress
from app.services.secure_runtime import decode_job, update_job_payload
from app.services.vault_session import vault_session

logger = logging.getLogger(__name__)


async def worker_loop(poll_seconds: float = 2.0) -> None:
    logger.info("Job worker started")
    while True:
        try:
            processed = await asyncio.to_thread(_process_one_job)
            if not processed:
                await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            logger.info("Job worker stopped")
            raise
        except Exception:
            logger.exception("Worker loop error")
            await asyncio.sleep(poll_seconds)


def _fail_stale_running_jobs(session: Session, dek: bytes) -> None:
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.sync_job_stale_seconds
    )
    stale_jobs = session.exec(
        select(Job).where(Job.status == JobStatus.RUNNING)
    ).all()
    changed = False
    for job in stale_jobs:
        if job.started_at is None or job.started_at > cutoff:
            continue
        job.status = JobStatus.FAILED
        job.finished_at = datetime.now(timezone.utc)
        update_job_payload(
            session,
            job,
            dek,
            error="Synchronization timed out. Check your credentials and try again.",
        )
        session.add(job)
        changed = True
    if changed:
        session.commit()
        clear_sync_progress()


def _process_one_job() -> bool:
    # No private job payload may be read or mutated before the vault has been
    # unlocked and its encrypted mirrors have passed the atomic audit.
    if not vault_session.is_unlocked():
        return False
    dek = vault_session.get_dek()
    if dek is None:
        return False
    with Session(engine) as session:
        _fail_stale_running_jobs(session, dek)
        job = session.exec(
            select(Job)
            .where(Job.status == JobStatus.PENDING)
            .order_by(Job.created_at)  # type: ignore[arg-type]
            .limit(1)
        ).first()
        if not job:
            return False
        private = decode_job(job, dek)

        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.started_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        session.refresh(job)

        error: str | None = None
        try:
            if job.job_type == JobType.SYNC:
                run_sync_job(session, job, payload=private.payload)
            elif job.job_type == JobType.MATCH:
                run_matching(session)
            elif job.job_type == JobType.CATEGORIZE:
                ids = private.payload.get("transaction_ids")
                apply_rules(session, ids)
            elif job.job_type == JobType.NORMALIZE:
                job.status = JobStatus.SKIPPED
                error = "Normalize runs inline during sync"
            else:
                job.status = JobStatus.SKIPPED
                error = f"Unknown job type: {job.job_type}"

            if job.status == JobStatus.RUNNING:
                job.status = JobStatus.DONE
        except Exception as exc:
            logger.exception("Job %s failed", job.id)
            error = str(exc)[:2000]
            if job.attempts >= job.max_attempts:
                job.status = JobStatus.FAILED
            else:
                job.status = JobStatus.PENDING

        job.finished_at = datetime.now(timezone.utc)
        update_job_payload(session, job, dek, error=error)
        session.add(job)
        session.commit()
        return True
