from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    UniqueConstraint,
    func,
)
from sqlmodel import Field, SQLModel

from app.models.enums import SyncStatus
from app.models.sa_types import str_enum


class SyncState(SQLModel, table=True):
    __tablename__ = "sync_state"
    __table_args__ = (
        UniqueConstraint("account_id"),
        Index("ix_sync_state_account_id", "account_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(
        sa_column=Column(ForeignKey("accounts.id"), nullable=False)
    )
    encrypted_payload: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    encryption_version: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    status: SyncStatus = Field(
        default=SyncStatus.IDLE,
        sa_column=Column(str_enum(SyncStatus), nullable=False),
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )
