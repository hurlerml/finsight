from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, LargeBinary, func
from sqlmodel import Field, SQLModel

from app.models.enums import JobStatus, JobType
from app.models.sa_types import str_enum


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_type: JobType = Field(sa_column=Column(str_enum(JobType), nullable=False, index=True))
    status: JobStatus = Field(
        default=JobStatus.PENDING,
        sa_column=Column(str_enum(JobStatus), nullable=False, index=True),
    )
    attempts: int = Field(default=0)
    max_attempts: int = Field(default=5)
    encrypted_payload: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    encryption_version: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )
    started_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    finished_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
