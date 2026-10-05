from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import TagType


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    tag_type: TagType = TagType.GENERAL
    color: str = Field(default="#b9c8ea", max_length=16)
    from_date: date | None = None
    to_date: date | None = None
    created_by: str = Field(default="manual", max_length=32)

    @model_validator(mode="after")
    def valid_period(self):
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must not be after to_date")
        return self


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    tag_type: TagType | None = None
    color: str | None = Field(default=None, max_length=16)
    from_date: date | None = None
    to_date: date | None = None


class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tag_type: TagType
    color: str
    from_date: date | None
    to_date: date | None
    created_by: str
    created_at: datetime


class TransactionTagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    tag_id: int
    assigned_by: str
    confidence: Decimal
    reason: str | None
    created_at: datetime
