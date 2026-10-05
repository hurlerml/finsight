from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, LargeBinary, func
from sqlmodel import Field, SQLModel


class AppSetting(SQLModel, table=True):
    """Singleton ciphertext payload for settings selected in the application."""

    __tablename__ = "app_settings"

    id: Optional[int] = Field(default=None, primary_key=True)
    encrypted_payload: Optional[bytes] = Field(
        default=None,
        sa_column=Column(LargeBinary, nullable=True),
    )
    encryption_version: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )
