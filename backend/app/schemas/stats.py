from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class CategoryBreakdown(BaseModel):
    category_id: int | None
    category_name: str
    category_slug: str | None = None
    color: str | None = None
    color_key: str | None = None
    icon: str | None = None
    amount: Decimal
    count: int


class StatsSummary(BaseModel):
    from_date: str
    to_date: str
    income: Decimal
    expense: Decimal
    spending: Decimal
    savings: Decimal
    net: Decimal
    transaction_count: int
    by_category: list[CategoryBreakdown]
    income_by_category: list[CategoryBreakdown] = Field(default_factory=list)


class TimeseriesSegment(BaseModel):
    key: str
    amount: Decimal
    category_slug: str | None = None
    color: str | None = None
    color_key: str | None = None
    icon: str | None = None


class TimeseriesBucket(BaseModel):
    period: str
    income_total: Decimal
    expense_total: Decimal
    income_segments: list[TimeseriesSegment]
    expense_segments: list[TimeseriesSegment]


class TimeseriesResponse(BaseModel):
    grain: str
    group_by: str
    from_date: str
    to_date: str
    buckets: list[TimeseriesBucket]


class FlowNode(BaseModel):
    name: str
    role: Literal["hub", "income", "expense", "saving"]
    category_slug: str | None = None
    color: str | None = None
    color_key: str | None = None
    icon: str | None = None
    group_by: str | None = None
    group_key: str | None = None
    account_source: str | None = None
    account_provider: str | None = None


class FlowLink(BaseModel):
    source: int
    target: int
    value: float


class FlowResponse(BaseModel):
    from_date: str
    to_date: str
    group_by: str = "category"
    nodes: list[FlowNode]
    links: list[FlowLink]
