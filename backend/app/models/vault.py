"""Vault metadata and encrypted connection credentials."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Index, Integer, LargeBinary, func, text
from sqlmodel import Field, SQLModel

from app.models.enums import AccountSource
from app.models.sa_types import str_enum


class VaultMeta(SQLModel, table=True):
    """Singleton row holding password and optional recovery wrappers for one DEK."""

    __tablename__ = "vault_meta"

    id: Optional[int] = Field(default=None, primary_key=True)
    salt: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    wrapped_dek: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    recovery_salt: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    recovery_wrapped_dek: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    recovery_version: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    recovery_confirmed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class Connection(SQLModel, table=True):
    """Encrypted adapter credentials. Plaintext secrets never stored."""

    __tablename__ = "connections"
    __table_args__ = (
        Index(
            "uq_connections_source_name_blind",
            "source",
            "name_blind",
            unique=True,
            postgresql_where=text("name_blind IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    source: AccountSource = Field(
        sa_column=Column(str_enum(AccountSource), nullable=False, index=True)
    )
    provider: str = Field(default="", max_length=64, index=True)
    secrets_encrypted: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )
    encrypted_payload: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    encryption_version: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    name_blind: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True, index=True)
    )
