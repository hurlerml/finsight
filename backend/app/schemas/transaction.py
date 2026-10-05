from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import CategorizedBy, LinkStatus, LinkType, TransactionKind


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    external_id: str
    booking_date: date
    amount: Decimal
    currency: str
    raw_text: str
    counterparty: str | None
    kind: TransactionKind
    category_id: int | None
    categorized_by: CategorizedBy | None
    categorization_reason: str | None
    created_at: datetime
    updated_at: datetime


class TransactionUpdate(BaseModel):
    category_id: int | None = None
    kind: TransactionKind | None = None


class TransactionPageRead(BaseModel):
    items: list[TransactionRead] = Field(default_factory=list)
    has_more: bool
    next_offset: int | None = None


class GroupedTransactionRead(TransactionRead):
    account_name: str
    account_source: str
    account_provider: str | None = None
    account_type: str


class TransactionGroupRead(BaseModel):
    id: int
    link_type: LinkType
    status: LinkStatus
    confidence: Decimal
    reason: str | None = None
    transactions: list[GroupedTransactionRead]
