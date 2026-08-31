from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.enums import ActorType, SourceType
from app.models.mixins import IdMixin, TimestampMixin, enum_column
from app.db import Base


class EvidenceRecord(Base, IdMixin, TimestampMixin):
    """One immutable, versioned record from a source system.

    A single table (not 7) keyed by source_type + a JSON payload: the 7
    sources have genuinely different shapes, but reconciliation needs to
    query/sort/merge across all of them by customer_id/order_id/time, which
    is far simpler against one table than 7-way UNIONs. Source-specific
    validation lives in app/ingestion/, not the schema.

    Corrections never overwrite: a corrected record is inserted as a new row
    with supersedes_id pointing at the one it replaces, which then gets
    is_superseded=True. Nothing is ever lost.
    """

    __tablename__ = "evidence_records"
    # No DB-level uniqueness on (source_type, external_ref, provenance_source):
    # corrections and duplicate-delivery detection deliberately insert further
    # rows sharing that triple (see supersedes_id / is_duplicate_of below).
    # "Current" means is_superseded == False; the ingestion service in
    # app/reconciliation/reconciler.py is what decides new vs. correction vs.
    # duplicate before writing a row.

    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    source_type: Mapped[SourceType] = enum_column(SourceType, index=True)
    # The source system's own identifier for this record -- the idempotency/
    # dedupe key. Combined with provenance_source it must be unique among
    # non-superseded rows (enforced in the ingestion service, not the DB,
    # since a *correction* intentionally reuses the same external_ref).
    external_ref: Mapped[str] = mapped_column(String(256), index=True)
    provenance_source: Mapped[str] = mapped_column(String(64))  # e.g. "freshdesk", "mock:pos", "freshservice"

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    recorded_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    payload: Mapped[dict] = mapped_column(JSON)

    actor_type: Mapped[ActorType] = enum_column(ActorType, default=ActorType.SYSTEM)

    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_records.id"), nullable=True)
    is_superseded: Mapped[bool] = mapped_column(Boolean, default=False)

    is_duplicate_of: Mapped[str | None] = mapped_column(ForeignKey("evidence_records.id"), nullable=True)
