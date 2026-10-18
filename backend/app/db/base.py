from enum import Enum as PyEnum

from sqlalchemy import JSON, Enum, MetaData, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# JSONB on PostgreSQL, plain JSON elsewhere (the unit tests run on SQLite).
JSONType = JSON().with_variant(JSONB(), "postgresql")

# 원 단위 가격은 정수지만 수정주가는 소수가 나올 수 있어 소수 4자리까지 둔다.
Price = Numeric(18, 4)


def str_enum(enum_cls: type[PyEnum], length: int) -> Enum:
    """Store a Python enum as VARCHAR of its values, without a DB-level CHECK or native enum."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
