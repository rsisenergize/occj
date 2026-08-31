from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import SourceType, UncertaintyFlagType
from app.models.mixins import IdMixin, TimestampMixin, enum_column


class CanonicalEvent(Base, IdMixin, TimestampMixin):
    """One reconciled timeline entry for a case, built from one EvidenceRecord.

    Kept 1:1 with the evidence record that produced it (not a separate
    merged/deduplicated fact) so provenance is always traceable; a
    correction updates effective_at/summary on the *same* CanonicalEvent
    rather than creating a duplicate timeline entry, but the superseded
    EvidenceRecord it originally pointed to is never lost.
    """

    __tablename__ = "canonical_events"

    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    evidence_record_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"))

    source_type: Mapped[SourceType] = enum_column(SourceType)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    summary: Mapped[str] = mapped_column(String(512))


class UncertaintyFlag(Base, IdMixin, TimestampMixin):
    """An explicit, queryable/resolvable record of missing, stale, duplicate,
    or contradictory evidence -- never hidden, never silently dropped."""

    __tablename__ = "uncertainty_flags"

    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    flag_type: Mapped[UncertaintyFlagType] = enum_column(UncertaintyFlagType, index=True)
    related_evidence_ids: Mapped[list] = mapped_column(JSON)  # list[str]
    description: Mapped[str] = mapped_column(String(1024))

    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(1024), nullable=True)
