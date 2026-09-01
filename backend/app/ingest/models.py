"""SQLAlchemy models for the new ingestion/reconciliation pipeline.

Table naming: every table here is prefixed `ingest_` (e.g. `ingest_orders`
rather than the spec's literal `order`) for two reasons: (1) `order` is a
reserved SQL keyword that would need quoting on every single query, and
(2) the prefix makes it unambiguous in a shared Postgres instance which
tables belong to this new pipeline versus the existing Case/EvidenceRecord
one -- both currently live in the same database. `customer` is deliberately
NOT duplicated here; this pipeline resolves against the existing
`app.models.case.Customer` table so there is one customer identity, not two
tables that could drift apart -- see README for the full rationale.

IDs are app-generated hex strings via IdMixin (not native UUID / DB-default
gen_random_uuid()), matching the rest of the codebase's SQLite/Postgres
portability convention -- see app/models/mixins.py.
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import DateTime as SADateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow
from app.ingest.enums import ConflictResolutionStatus, IngestSourceSystem, TimelineStatus
from app.models.mixins import IdMixin, TimestampMixin, enum_column


class Timeline(Base, IdMixin, TimestampMixin):
    """A customer's open investigation thread. Auto-created by the
    reconciliation engine the first time evidence arrives for a customer
    with no open timeline -- there is no separate "create timeline" API,
    mirroring the spec's "find open timeline for this customer; create if
    none exists." A timeline can span multiple orders (TIMELINE ||--o{
    ORDER)."""

    __tablename__ = "ingest_timelines"

    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[TimelineStatus] = enum_column(TimelineStatus, default=TimelineStatus.OPEN)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)


class IngestOrder(Base, IdMixin, TimestampMixin):
    """Resolved order entity -- table name `ingest_orders`, Python class
    `IngestOrder` (not `Order`) to avoid colliding with any future model
    named Order in the existing pipeline."""

    __tablename__ = "ingest_orders"
    __table_args__ = (UniqueConstraint("order_ref", name="uq_ingest_orders_order_ref"),)

    timeline_id: Mapped[str] = mapped_column(ForeignKey("ingest_timelines.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    order_ref: Mapped[str] = mapped_column(String(256), index=True)  # external order id from OMS


class OrderVersion(Base, IdMixin):
    """Append-only order-status lifecycle history for one order. Only OMS's
    own order_status fact_type writes here (see engine.py) -- payments,
    fulfilment, returns etc. that merely *reference* an order_id go to
    Log/LogVersion instead, linked via Log.order_id. This is an explicit
    assumption (the spec's schema doesn't say which facts qualify); the
    alternative (any order-referencing fact writes an order_version) would
    make order_version a general "anything touched this order" log rather
    than a specific status lifecycle -- see README.

    No TimestampMixin: `created_at` here IS the row-creation time, but the
    business-meaningful timestamps are event_time/received_time below, so
    they're modeled explicitly rather than implied."""

    __tablename__ = "ingest_order_versions"
    __table_args__ = (UniqueConstraint("order_id", "version_no", name="uq_order_version_no"),)

    order_id: Mapped[str] = mapped_column(ForeignKey("ingest_orders.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)

    event_time: Mapped[datetime] = mapped_column(SADateTime(timezone=True))
    received_time: Mapped[datetime] = mapped_column(SADateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64))
    provenance: Mapped[str] = mapped_column(String(64))  # source_system, or "human:<user_id>"

    # Always NULL in this implementation: setting it after the fact would be
    # an UPDATE on an already-inserted row, which the Postgres append-only
    # trigger (see the migration) rejects unconditionally -- deliberately,
    # since a trigger that made an exception for exactly this one column
    # would be a much weaker guarantee. "Latest version" is instead found
    # via MAX(version_no), which needs no mutation. Kept in the schema
    # because the spec's ER diagram references it and a future consumer
    # (e.g. a relaxed non-Postgres deployment) may choose to populate it.
    superseded_by: Mapped[str | None] = mapped_column(ForeignKey("ingest_order_versions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(SADateTime(timezone=True), default=utcnow)


class Log(Base, IdMixin, TimestampMixin):
    """A grouping slot for one recurring fact about a timeline/order --
    e.g. "the fulfilment_update history for order X". Identity key is
    (timeline_id, order_id, source_system, fact_type): see engine.py's
    _resolve_log for why (the canonical envelope has no source-system
    idempotency key, so log identity is structural, not delivery-based;
    each new event under a given slot becomes a new LogVersion, and
    conflict detection -- not "is this a correction" -- is what decides
    whether two versions actually disagree)."""

    __tablename__ = "ingest_logs"
    __table_args__ = (
        UniqueConstraint(
            "timeline_id", "order_id", "source_system", "fact_type", name="uq_log_identity"
        ),
    )

    timeline_id: Mapped[str] = mapped_column(ForeignKey("ingest_timelines.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("ingest_orders.id"), nullable=True, index=True)

    source_system: Mapped[IngestSourceSystem] = enum_column(IngestSourceSystem, index=True)
    fact_type: Mapped[str] = mapped_column(String(128), index=True)


class LogVersion(Base, IdMixin):
    """Append-only occurrence history for one Log slot."""

    __tablename__ = "ingest_log_versions"
    __table_args__ = (UniqueConstraint("log_id", "version_no", name="uq_log_version_no"),)

    log_id: Mapped[str] = mapped_column(ForeignKey("ingest_logs.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)

    event_time: Mapped[datetime] = mapped_column(SADateTime(timezone=True))
    received_time: Mapped[datetime] = mapped_column(SADateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64))
    provenance: Mapped[str] = mapped_column(String(64))

    # Always NULL -- see OrderVersion.superseded_by's comment above; same
    # reasoning applies here (the append-only trigger covers this table too).
    superseded_by: Mapped[str | None] = mapped_column(ForeignKey("ingest_log_versions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(SADateTime(timezone=True), default=utcnow)


class Conflict(Base, IdMixin):
    __tablename__ = "ingest_conflicts"

    timeline_id: Mapped[str] = mapped_column(ForeignKey("ingest_timelines.id"), index=True)
    fact_type: Mapped[str] = mapped_column(String(128))
    resolution_status: Mapped[ConflictResolutionStatus] = enum_column(
        ConflictResolutionStatus, default=ConflictResolutionStatus.UNRESOLVED
    )
    resolution_rule: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(SADateTime(timezone=True), default=utcnow)


class ConflictReference(Base, IdMixin):
    """Join table: which specific versions are in conflict. Exactly one of
    log_version_id / order_version_id is set per row."""

    __tablename__ = "ingest_conflict_references"

    conflict_id: Mapped[str] = mapped_column(ForeignKey("ingest_conflicts.id"), index=True)
    log_version_id: Mapped[str | None] = mapped_column(ForeignKey("ingest_log_versions.id"), nullable=True)
    order_version_id: Mapped[str | None] = mapped_column(ForeignKey("ingest_order_versions.id"), nullable=True)


class Outbox(Base, IdMixin, TimestampMixin):
    """Written in the same DB transaction as the log/order-version + conflict
    writes it describes. Nothing consumes this yet -- publishing it to a
    downstream relay is explicitly out of scope for this module (per spec
    §1's flow diagram); this table exists so that seam is real and testable
    (see the outbox-atomicity test) rather than a TODO comment."""

    __tablename__ = "ingest_outbox"

    aggregate_id: Mapped[str] = mapped_column(String(64), index=True)  # timeline_id
    event_type: Mapped[str] = mapped_column(String(64))  # log.ingested | order.updated | conflict.detected
    payload: Mapped[dict] = mapped_column(JSON)
    published: Mapped[bool] = mapped_column(Boolean, default=False)


class DeadLetter(Base, IdMixin, TimestampMixin):
    """A normalized event the streamer's Reconciliation Engine handler
    failed to process after MAX_RETRIES attempts. Never blocks the
    streamer -- see EventStreamer._deliver in streamer.py."""

    __tablename__ = "ingest_dead_letters"

    raw_event: Mapped[dict] = mapped_column(JSON)
    error_reason: Mapped[str] = mapped_column(String(1024))
    attempt_count: Mapped[int] = mapped_column(Integer)
    failed_at: Mapped[datetime] = mapped_column(SADateTime(timezone=True), default=utcnow)
