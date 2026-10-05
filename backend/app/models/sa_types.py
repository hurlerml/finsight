"""SQLAlchemy helpers — store Python enums as VARCHAR (matches Alembic migrations)."""

from enum import Enum
from typing import Type

from sqlalchemy import Enum as SAEnum


def str_enum(enum_cls: Type[Enum]):
    return SAEnum(
        enum_cls,
        values_callable=lambda x: [e.value for e in x],
        native_enum=False,
        length=32,
    )
