"""Public (non-sensitive) inflation reference data."""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Column, DateTime, Numeric, String, UniqueConstraint, func
from sqlmodel import Field, SQLModel


class InflationIndex(SQLModel, table=True):
    __tablename__ = "inflation_indices"
    __table_args__ = (UniqueConstraint("country", "month", "source", name="uq_inflation_country_month_source"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    country: str = Field(default="DE", max_length=2, index=True)
    currency: str = Field(default="EUR", max_length=3)
    month: str = Field(max_length=7, index=True)  # YYYY-MM
    index_value: Decimal = Field(sa_column=Column(Numeric(12, 6), nullable=False))
    source: str = Field(default="eurostat", max_length=32)
    fetched_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
