from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, LargeBinary, func, text
from sqlmodel import Field, SQLModel

from app.models.enums import AccountSource
from app.models.sa_types import str_enum


class Account(SQLModel, table=True):
    __tablename__ = "accounts"
    __table_args__ = (
        Index(
            "uq_accounts_source_external_blind",
            "source",
            "external_id_blind",
            unique=True,
            postgresql_where=text("external_id_blind IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    connection_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            ForeignKey(
                "connections.id",
                name="fk_accounts_connection_id",
                ondelete="SET NULL",
            ),
            nullable=True,
            index=True,
        ),
    )
    source: AccountSource = Field(sa_column=Column(str_enum(AccountSource), nullable=False, index=True))
    is_active: bool = Field(default=True)
    encrypted_payload: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    encryption_version: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    external_id_blind: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True, index=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )
