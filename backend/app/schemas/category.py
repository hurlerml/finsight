from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


CategoryColorKey = Literal[
    "housing",
    "groceries",
    "dining",
    "mobility",
    "health",
    "subscriptions",
    "shopping",
    "leisure",
    "travel",
    "family",
    "education",
    "savings",
    "finance",
    "income",
    "other",
]
CategoryIconKey = Literal[
    "house",
    "basket",
    "utensils",
    "car",
    "heart",
    "repeat",
    "bag",
    "culture",
    "plane",
    "users",
    "education",
    "savings",
    "finance",
    "income",
    "other",
]


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=3, max_length=500)
    color_key: CategoryColorKey = "other"
    icon: CategoryIconKey = "other"

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, min_length=3, max_length=500)
    color_key: CategoryColorKey | None = None
    icon: CategoryIconKey | None = None

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    color: str
    color_key: str
    icon: str
    description: str
    is_system: bool
    created_at: datetime


class CategoryImpactRead(BaseModel):
    assigned: int
    automatic: int
    manual: int
    uncategorized: int


class CategoryMutationRead(BaseModel):
    category: CategoryRead | None = None
    reset_count: int = 0
    rules_applied: int = 0
    queued_for_agent: int = 0


class CategoryRuleCreate(BaseModel):
    category_id: int
    pattern: str = Field(min_length=1, max_length=512)
    is_regex: bool = False
    priority: int = 100
    is_active: bool = True


class CategoryRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    pattern: str
    is_regex: bool
    priority: int
    is_active: bool
    created_at: datetime
