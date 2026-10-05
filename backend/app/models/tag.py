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
    text,
)
from sqlmodel import Field, SQLModel


class Tag(SQLModel, table=True):
    __tablename__ = "tags"
    __table_args__ = (
        Index(
            "uq_tags_name_blind",
            "name_blind",
            unique=True,
            postgresql_where=text("name_blind IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    encrypted_payload: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    encryption_version: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    name_blind: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True, index=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )


class TransactionTag(SQLModel, table=True):
    __tablename__ = "transaction_tags"
    __table_args__ = (UniqueConstraint("transaction_id", "tag_id", name="uq_transaction_tag"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: int = Field(
        sa_column=Column(
            ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    tag_id: int = Field(
        sa_column=Column(
            ForeignKey("tags.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    encrypted_payload: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    encryption_version: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
