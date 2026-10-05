from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, LargeBinary, func
from sqlmodel import Field, SQLModel


class AccountBalanceSnapshot(SQLModel, table=True):
    __tablename__ = "account_balance_snapshots"
    __table_args__ = (
        Index("ix_account_balance_account_captured", "account_id", "captured_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(
        sa_column=Column(
            ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    captured_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    encrypted_payload: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    encryption_version: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
