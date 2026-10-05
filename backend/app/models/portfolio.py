from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    UniqueConstraint,
    func,
    text,
)
from sqlmodel import Field, SQLModel

from app.models.enums import AccountSource
from app.models.sa_types import str_enum


class Portfolio(SQLModel, table=True):
    __tablename__ = "portfolios"
    __table_args__ = (
        Index(
            "uq_portfolios_source_external_blind",
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
            ForeignKey("connections.id", ondelete="CASCADE"), nullable=True, index=True
        ),
    )
    source: AccountSource = Field(
        sa_column=Column(str_enum(AccountSource), nullable=False, index=True)
    )
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


class AssetPositionSnapshot(SQLModel, table=True):
    __tablename__ = "asset_position_snapshots"
    __table_args__ = (
        Index("ix_asset_position_portfolio_captured", "portfolio_id", "captured_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(
        sa_column=Column(
            ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
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


class AssetPricePoint(SQLModel, table=True):
    __tablename__ = "asset_price_points"
    __table_args__ = (
        UniqueConstraint(
            "source", "external_id", "exchange", "timestamp",
            name="uq_asset_price_source_instrument_time",
        ),
        Index("ix_asset_price_instrument_time", "source", "external_id", "timestamp"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    source: AccountSource = Field(
        sa_column=Column(str_enum(AccountSource), nullable=False, index=True)
    )
    external_id: str = Field(max_length=255, index=True)
    exchange: str = Field(max_length=32)
    timestamp: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    open: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(18, 6)))
    high: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(18, 6)))
    low: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(18, 6)))
    close: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    adjusted: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(18, 6)))
    volume: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(28, 6)))
    currency: str = Field(default="EUR", max_length=3)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )


class PortfolioValuePoint(SQLModel, table=True):
    __tablename__ = "portfolio_value_points"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "history_range", "timestamp",
            name="uq_portfolio_value_range_time",
        ),
        Index("ix_portfolio_value_portfolio_time", "portfolio_id", "timestamp"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(
        sa_column=Column(
            ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    timestamp: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    history_range: str = Field(default="max", max_length=8, index=True)
    encrypted_payload: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    encryption_version: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )


class AssetTrade(SQLModel, table=True):
    __tablename__ = "asset_trades"
    __table_args__ = (
        Index("ix_asset_trade_portfolio_time", "portfolio_id", "timestamp"),
        Index(
            "uq_asset_trades_portfolio_external_blind",
            "portfolio_id",
            "external_id_blind",
            unique=True,
            postgresql_where=text("external_id_blind IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(
        sa_column=Column(
            ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    timestamp: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
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
