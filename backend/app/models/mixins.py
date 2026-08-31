"""Shared column mixins.

UUID primary keys are stored as hex strings (not native UUID/PG-specific
types) so the same model definitions work unmodified on SQLite (dev) and
Postgres/Supabase (prod) -- portability was an explicit design goal.
"""
import uuid
from datetime import datetime
from enum import StrEnum
from typing import TypeVar

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db import utcnow


def new_id() -> str:
    return uuid.uuid4().hex


E = TypeVar("E", bound=StrEnum)


def enum_column(enum_cls: type[E], **kwargs):
    """A str-backed enum column that actually round-trips to the enum class
    on read (plain String(32) columns do not -- SQLAlchemy hands back a raw
    str after a query, which breaks any code calling .value on it).
    native_enum=False stores it as VARCHAR everywhere (SQLite and Postgres
    alike) instead of a Postgres CREATE TYPE, so adding a new enum member
    later is a code change, not a migration that alters a PG enum type."""
    return mapped_column(
        SAEnum(enum_cls, values_callable=lambda e: [m.value for m in e], native_enum=False, length=64),
        **kwargs,
    )


class IdMixin:
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
