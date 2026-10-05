from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AccountSource, AccountType


class AccountCreate(BaseModel):
    source: AccountSource
    external_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    currency: str = Field(default="EUR", max_length=3)
    account_type: AccountType = AccountType.CHECKING
    iban: str | None = None


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    connection_id: int | None
    source: AccountSource
    external_id: str
    name: str
    currency: str
    account_type: AccountType
    iban: str | None
    is_active: bool
    current_balance: Decimal | None
    available_balance: Decimal | None
    balance_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime
