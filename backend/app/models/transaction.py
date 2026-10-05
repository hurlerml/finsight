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

from app.models.enums import LinkStatus, LinkType
from app.models.sa_types import str_enum


class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"
    __table_args__ = (
        Index(
            "uq_transactions_account_external_blind",
            "account_id",
            "external_id_blind",
            unique=True,
            postgresql_where=text("external_id_blind IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="accounts.id", index=True)
    encrypted_payload: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    encryption_version: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    booking_month_blind: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True, index=True)
    )
    external_id_blind: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True, index=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class TransactionEmbedding(SQLModel, table=True):
    __tablename__ = "transaction_embeddings"
    __table_args__ = (UniqueConstraint("transaction_id", name="uq_transaction_embedding_transaction"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: int = Field(
        sa_column=Column(ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    model_name: str = Field(max_length=160)
    dimensions: int = Field(default=0)
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
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class TransactionLink(SQLModel, table=True):
    __tablename__ = "transaction_links"
    __table_args__ = (
        UniqueConstraint("transaction_a_id", "transaction_b_id", "link_type", name="uq_tx_link"),
        Index("ix_transaction_links_a", "transaction_a_id"),
        Index("ix_transaction_links_b", "transaction_b_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_a_id: int = Field(
        sa_column=Column(ForeignKey("transactions.id"), nullable=False)
    )
    transaction_b_id: int = Field(
        sa_column=Column(ForeignKey("transactions.id"), nullable=False)
    )
    transfer_transaction_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            ForeignKey(
                "transactions.id",
                name="fk_transaction_links_transfer_transaction_id",
                ondelete="SET NULL",
            ),
            nullable=True,
            index=True,
        ),
    )
    link_type: LinkType = Field(sa_column=Column(str_enum(LinkType), nullable=False))
    status: LinkStatus = Field(
        default=LinkStatus.CONFIRMED,
        sa_column=Column(
            str_enum(LinkStatus), nullable=False, index=True, server_default="confirmed"
        ),
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
