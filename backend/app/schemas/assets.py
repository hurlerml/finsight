from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import AccountSource


class AssetPositionRead(BaseModel):
    id: int
    external_id: str
    isin: str | None
    name: str
    asset_type: str | None
    quantity: Decimal
    average_buy_in: Decimal | None
    current_price: Decimal | None
    market_value: Decimal | None
    cost_value: Decimal | None
    gain_value: Decimal | None
    gain_percent: Decimal | None
    performance_cost_value: Decimal | None = None
    currency: str


class PortfolioRead(BaseModel):
    id: int
    connection_id: int | None
    source: AccountSource
    name: str
    currency: str
    last_synced_at: datetime | None
    total_market_value: Decimal
    total_cost_value: Decimal
    total_gain_value: Decimal
    total_gain_percent: Decimal | None = None
    performance_cost_value: Decimal = Decimal("0")
    priced_positions: int
    positions: list[AssetPositionRead]


class AssetsOverviewRead(BaseModel):
    portfolios: list[PortfolioRead]


class AssetHistoryPointRead(BaseModel):
    timestamp: datetime
    value: Decimal
    invested_value: Decimal | None = None
    # Providers such as Trade Republic return the relative performance for
    # every chart sample.  It is deliberately kept separate from
    # ``invested_value`` because the provider's denominator is time-weighted
    # portfolio capital, not the current cost basis.
    performance_percent: Decimal | None = None


class AssetHistoryCalibrationRead(BaseModel):
    offset: Decimal
    mean_absolute_error: Decimal
    max_absolute_error: Decimal
    overlap_points: int
    matched: bool


class AssetHistoryRead(BaseModel):
    kind: str
    label: str
    currency: str
    estimated: bool = False
    source: str = "calculated"
    calibration: AssetHistoryCalibrationRead | None = None
    points: list[AssetHistoryPointRead]
