"""Reconciliation Engine: the Streamer's consumer. On one normalized
CanonicalEvent, in a single atomic transaction (the caller commits once at
the end -- see app/ingest/subscriber.py):

  1. resolve customer
  2. resolve timeline (open, or create)
  3. resolve order (if order_id present)
  4. write the append-only version row (order_version for order_status,
     log_version for everything else)
  5. detect conflicts against the prior version (materiality.py)
  6. attempt auto-resolution (conflict_strategies.py) -- never deletes the
     losing version
  7. write the outbox row(s)

No LLM/ML anywhere in this module -- every decision here is deterministic.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.ingest.conflict_strategies import ConflictContext, try_resolve
from app.ingest.enums import ConflictResolutionStatus, TimelineStatus
from app.ingest.materiality import is_material_change
from app.ingest.models import (
    Conflict,
    ConflictReference,
    IngestOrder,
    Log,
    LogVersion,
    Outbox,
    OrderVersion,
    Timeline,
)
from app.ingest.schemas import CanonicalEvent
from app.models.case import Customer

ORDER_STATUS_FACT_TYPE = "order_status"


class UnresolvableIdentityError(Exception):
    """Raised when an event has no customer_id and its order_id doesn't
    resolve to an already-known order (e.g. a WMS event, which per spec
    §2.1 may carry only order_id, arriving before OMS has ever told us
    about that order). Caught by the streamer's normal retry/dead-letter
    path like any other handler failure -- see subscriber.py."""


async def handle_event(session: AsyncSession, event: CanonicalEvent) -> None:
    customer = await _resolve_customer(session, event)
    if customer is None:
        raise UnresolvableIdentityError(
            f"event has no customer_id and order_id={event.order_id!r} does not resolve to a known order"
        )

    timeline = await _resolve_timeline(session, customer)
    order = await _resolve_order(session, event, timeline, customer) if event.order_id else None

    if event.fact_type == ORDER_STATUS_FACT_TYPE and order is not None:
        version, conflict = await _write_order_version(session, order, timeline, event)
        event_type = "order.updated"
    else:
        version, conflict = await _write_log_version(session, timeline, customer, order, event)
        event_type = "log.ingested"

    await _write_outbox(session, timeline, event, event_type, version.id, conflict)


async def _resolve_customer(session: AsyncSession, event: CanonicalEvent) -> Customer | None:
    if event.customer_id:
        existing = await session.scalar(select(Customer).where(Customer.external_customer_id == event.customer_id))
        if existing is not None:
            return existing
        customer = Customer(external_customer_id=event.customer_id, display_name=event.customer_id, tier="standard")
        session.add(customer)
        await session.flush()
        return customer
    if event.order_id:
        existing_order = await session.scalar(select(IngestOrder).where(IngestOrder.order_ref == event.order_id))
        if existing_order is not None:
            return await session.get(Customer, existing_order.customer_id)
    return None


async def _resolve_timeline(session: AsyncSession, customer: Customer) -> Timeline:
    existing = await session.scalar(
        select(Timeline)
        .where(Timeline.customer_id == customer.id, Timeline.status == TimelineStatus.OPEN)
        .order_by(Timeline.created_at.desc())
    )
    if existing is not None:
        return existing
    timeline = Timeline(customer_id=customer.id)
    session.add(timeline)
    await session.flush()
    return timeline


async def _resolve_order(
    session: AsyncSession, event: CanonicalEvent, timeline: Timeline, customer: Customer
) -> IngestOrder:
    existing = await session.scalar(select(IngestOrder).where(IngestOrder.order_ref == event.order_id))
    if existing is not None:
        return existing
    order = IngestOrder(timeline_id=timeline.id, customer_id=customer.id, order_ref=event.order_id)
    session.add(order)
    await session.flush()
    return order


async def _latest_order_version(session: AsyncSession, order_id: str) -> OrderVersion | None:
    return await session.scalar(
        select(OrderVersion).where(OrderVersion.order_id == order_id).order_by(OrderVersion.version_no.desc())
    )


async def _write_order_version(
    session: AsyncSession, order: IngestOrder, timeline: Timeline, event: CanonicalEvent
) -> tuple[OrderVersion, Conflict | None]:
    latest = await _latest_order_version(session, order.id)
    version = OrderVersion(
        order_id=order.id,
        version_no=(latest.version_no + 1) if latest else 1,
        status=str(event.payload.get("status", event.fact_type)),
        payload=event.payload,
        event_time=event.event_time,
        received_time=event.received_time,
        timezone=event.timezone,
        provenance=event.source_system.value,
        created_at=utcnow(),
    )
    session.add(version)
    await session.flush()

    conflict = None
    if latest is not None and is_material_change(event.fact_type, latest.payload, event.payload):
        conflict = await _raise_conflict(
            session,
            timeline,
            event.fact_type,
            existing_ref=(None, latest.id),
            new_ref=(None, version.id),
            existing_provenance=latest.provenance,
            new_provenance=event.source_system.value,
            existing_payload=latest.payload,
            new_payload=event.payload,
        )
    return version, conflict


async def _resolve_log(session: AsyncSession, timeline: Timeline, customer: Customer, order: IngestOrder | None, event: CanonicalEvent) -> Log:
    order_id = order.id if order is not None else None
    existing = await session.scalar(
        select(Log).where(
            Log.timeline_id == timeline.id,
            Log.order_id == order_id,
            Log.source_system == event.source_system,
            Log.fact_type == event.fact_type,
        )
    )
    if existing is not None:
        return existing
    log = Log(
        timeline_id=timeline.id,
        customer_id=customer.id,
        order_id=order_id,
        source_system=event.source_system,
        fact_type=event.fact_type,
    )
    session.add(log)
    await session.flush()
    return log


async def _write_log_version(
    session: AsyncSession, timeline: Timeline, customer: Customer, order: IngestOrder | None, event: CanonicalEvent
) -> tuple[LogVersion, Conflict | None]:
    log = await _resolve_log(session, timeline, customer, order, event)
    latest = await session.scalar(
        select(LogVersion).where(LogVersion.log_id == log.id).order_by(LogVersion.version_no.desc())
    )
    version = LogVersion(
        log_id=log.id,
        version_no=(latest.version_no + 1) if latest else 1,
        payload=event.payload,
        event_time=event.event_time,
        received_time=event.received_time,
        timezone=event.timezone,
        provenance=event.source_system.value,
        created_at=utcnow(),
    )
    session.add(version)
    await session.flush()

    conflict = None
    if latest is not None and is_material_change(event.fact_type, latest.payload, event.payload):
        conflict = await _raise_conflict(
            session,
            timeline,
            event.fact_type,
            existing_ref=(latest.id, None),
            new_ref=(version.id, None),
            existing_provenance=latest.provenance,
            new_provenance=event.source_system.value,
            existing_payload=latest.payload,
            new_payload=event.payload,
        )
    return version, conflict


async def _raise_conflict(
    session: AsyncSession,
    timeline: Timeline,
    fact_type: str,
    *,
    existing_ref: tuple[str | None, str | None],
    new_ref: tuple[str | None, str | None],
    existing_provenance: str,
    new_provenance: str,
    existing_payload: dict,
    new_payload: dict,
) -> Conflict:
    outcome = try_resolve(
        ConflictContext(
            fact_type=fact_type,
            existing_provenance=existing_provenance,
            existing_payload=existing_payload,
            new_provenance=new_provenance,
            new_payload=new_payload,
        )
    )
    conflict = Conflict(
        timeline_id=timeline.id,
        fact_type=fact_type,
        resolution_status=ConflictResolutionStatus.RESOLVED if outcome else ConflictResolutionStatus.UNRESOLVED,
        resolution_rule=outcome.rule_name if outcome else None,
        detected_at=utcnow(),
    )
    session.add(conflict)
    await session.flush()
    for log_version_id, order_version_id in (existing_ref, new_ref):
        session.add(
            ConflictReference(conflict_id=conflict.id, log_version_id=log_version_id, order_version_id=order_version_id)
        )
    await session.flush()
    return conflict


async def _write_outbox(
    session: AsyncSession,
    timeline: Timeline,
    event: CanonicalEvent,
    event_type: str,
    version_id: str,
    conflict: Conflict | None,
) -> None:
    session.add(
        Outbox(
            aggregate_id=timeline.id,
            event_type=event_type,
            payload={"fact_type": event.fact_type, "source_system": event.source_system.value, "version_id": version_id},
        )
    )
    if conflict is not None:
        session.add(
            Outbox(
                aggregate_id=timeline.id,
                event_type="conflict.detected",
                payload={
                    "conflict_id": conflict.id,
                    "fact_type": event.fact_type,
                    "resolution_status": conflict.resolution_status.value,
                },
            )
        )
