from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import ActorType
from app.models.mixins import IdMixin, TimestampMixin, enum_column


class AuditEntry(Base, IdMixin, TimestampMixin):
    """Append-only. Every fact ingested, inference drawn, input given, action
    taken, and decision made writes exactly one row here. Replay = fetch all
    entries for a case ordered by occurred_at and fold them into a state
    snapshot as of any point in time (see app/audit/service.py)."""

    __tablename__ = "audit_entries"

    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id"), nullable=True, index=True)

    entity_type: Mapped[str] = mapped_column(String(64))  # "evidence_record" | "hypothesis" | "action_request" | ...
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    event: Mapped[str] = mapped_column(String(64))  # "ingested" | "created" | "superseded" | "approved" | ...

    actor_type: Mapped[ActorType] = enum_column(ActorType, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)  # user id, or connector/engine name

    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
