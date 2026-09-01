"""Read-only Debug API: verifies the ingestion pipeline is working end to
end (events arrived, normalized correctly, grouped correctly, conflicts
detected correctly, nothing stuck/lost). NOT the investigator-facing
workspace -- that's the existing /cases API, a separate, later concern.

Every route here is a GET; nothing here ever mutates pipeline data (spec
§4.4/§7's explicit constraint). Gated behind the ADMIN role, same as the
existing "seed demo data" action -- see README for why a shared dev
token/tighter gate is needed before a shared/staging environment.

Response shapes are plain dicts rather than typed Pydantic response
models: this is internal debug tooling, not the versioned investigator
API, so the lighter-weight approach is a deliberate scope choice."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_roles
from app.db import get_session, utcnow
from app.ingest.enums import IngestSourceSystem
from app.ingest.models import Conflict, ConflictReference, DeadLetter, IngestOrder, Log, LogVersion, Outbox, OrderVersion, Timeline
from app.models.auth import User
from app.models.case import Customer
from app.models.enums import UserRole

router = APIRouter(prefix="/debug", tags=["ingest-debug"])


def _order_version_out(v: OrderVersion, order: IngestOrder | None = None) -> dict:
    return {
        "id": v.id,
        "kind": "order_version",
        "version_no": v.version_no,
        "status": v.status,
        "payload": v.payload,
        "event_time": v.event_time,
        "received_time": v.received_time,
        "timezone": v.timezone,
        "provenance": v.provenance,
        "created_at": v.created_at,
        "order_id": order.order_ref if order is not None else None,
    }


def _log_version_out(v: LogVersion, log: Log, order_ref: str | None = None) -> dict:
    return {
        "id": v.id,
        "kind": "log_version",
        "log_id": log.id,
        "fact_type": log.fact_type,
        "source_system": log.source_system.value,
        "version_no": v.version_no,
        "payload": v.payload,
        "event_time": v.event_time,
        "received_time": v.received_time,
        "timezone": v.timezone,
        "provenance": v.provenance,
        "created_at": v.created_at,
        "order_id": order_ref,  # human-readable order_ref, not the internal FK
    }


@router.get("/events/recent")
async def recent_events(
    limit: int = Query(default=50, le=200),
    source: IngestSourceSystem | None = None,
    customer_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> dict:
    """Live feed of recently ingested log_version/order_version rows,
    across both kinds -- the debug UI's "Live Ingestion Feed"."""
    customer_pk: str | None = None
    if customer_id:
        customer = await session.scalar(select(Customer).where(Customer.external_customer_id == customer_id))
        if customer is None:
            return {"events": []}
        customer_pk = customer.id

    log_q = (
        select(LogVersion, Log, IngestOrder)
        .join(Log, LogVersion.log_id == Log.id)
        .outerjoin(IngestOrder, Log.order_id == IngestOrder.id)
    )
    if source is not None:
        log_q = log_q.where(Log.source_system == source)
    if customer_pk is not None:
        log_q = log_q.where(Log.customer_id == customer_pk)
    log_rows = (await session.execute(log_q.order_by(LogVersion.created_at.desc()).limit(limit))).all()

    order_q = select(OrderVersion, IngestOrder).join(IngestOrder, OrderVersion.order_id == IngestOrder.id)
    if source is not None and source != IngestSourceSystem.OMS:
        order_rows: list = []
    else:
        if customer_pk is not None:
            order_q = order_q.where(IngestOrder.customer_id == customer_pk)
        order_rows = (await session.execute(order_q.order_by(OrderVersion.created_at.desc()).limit(limit))).all()

    events = [_log_version_out(v, log, order.order_ref if order else None) for v, log, order in log_rows] + [
        _order_version_out(v, order) for v, order in order_rows
    ]
    events.sort(key=lambda e: e["created_at"], reverse=True)
    return {"events": events[:limit]}


@router.get("/timeline/{identifier}")
async def timeline_explorer(
    identifier: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> dict:
    """Grouped view for one customer_id (external) or order_ref: Timeline ->
    Orders -> Logs, with version history and open conflicts."""
    customer = await session.scalar(select(Customer).where(Customer.external_customer_id == identifier))
    if customer is None:
        order = await session.scalar(select(IngestOrder).where(IngestOrder.order_ref == identifier))
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No customer or order matches this identifier")
        customer = await session.get(Customer, order.customer_id)

    timelines = list(
        await session.scalars(select(Timeline).where(Timeline.customer_id == customer.id).order_by(Timeline.created_at))
    )
    out_timelines = []
    for tl in timelines:
        orders = list(await session.scalars(select(IngestOrder).where(IngestOrder.timeline_id == tl.id)))
        orders_out = []
        for o in orders:
            versions = list(
                await session.scalars(
                    select(OrderVersion).where(OrderVersion.order_id == o.id).order_by(OrderVersion.version_no)
                )
            )
            orders_out.append({"id": o.id, "order_ref": o.order_ref, "versions": [_order_version_out(v) for v in versions]})

        logs = list(await session.scalars(select(Log).where(Log.timeline_id == tl.id)))
        logs_out = []
        for log in logs:
            versions = list(
                await session.scalars(
                    select(LogVersion).where(LogVersion.log_id == log.id).order_by(LogVersion.version_no)
                )
            )
            logs_out.append(
                {
                    "id": log.id,
                    "fact_type": log.fact_type,
                    "source_system": log.source_system.value,
                    "order_id": log.order_id,
                    "versions": [_log_version_out(v, log) for v in versions],
                }
            )

        conflicts = list(await session.scalars(select(Conflict).where(Conflict.timeline_id == tl.id)))
        out_timelines.append(
            {
                "id": tl.id,
                "status": tl.status.value,
                "created_at": tl.created_at,
                "orders": orders_out,
                "logs": sorted(logs_out, key=lambda entry: entry["versions"][0]["event_time"] if entry["versions"] else tl.created_at),
                "conflicts": [
                    {"id": c.id, "fact_type": c.fact_type, "resolution_status": c.resolution_status.value, "resolution_rule": c.resolution_rule, "detected_at": c.detected_at}
                    for c in conflicts
                ],
            }
        )

    return {
        "customer": {"id": customer.id, "external_customer_id": customer.external_customer_id, "display_name": customer.display_name},
        "timelines": out_timelines,
    }


@router.get("/conflicts")
async def list_conflicts(
    status_filter: str | None = Query(default="unresolved", alias="status"),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> dict:
    q = select(Conflict)
    if status_filter:
        q = q.where(Conflict.resolution_status == status_filter)
    conflicts = list(await session.scalars(q.order_by(Conflict.detected_at.desc())))

    out = []
    for c in conflicts:
        refs = list(await session.scalars(select(ConflictReference).where(ConflictReference.conflict_id == c.id)))
        versions = []
        for ref in refs:
            if ref.log_version_id:
                lv = await session.get(LogVersion, ref.log_version_id)
                if lv:
                    log = await session.get(Log, lv.log_id)
                    versions.append(_log_version_out(lv, log))
            elif ref.order_version_id:
                ov = await session.get(OrderVersion, ref.order_version_id)
                if ov:
                    versions.append(_order_version_out(ov))
        out.append(
            {
                "id": c.id,
                "timeline_id": c.timeline_id,
                "fact_type": c.fact_type,
                "resolution_status": c.resolution_status.value,
                "resolution_rule": c.resolution_rule,
                "detected_at": c.detected_at,
                "versions": versions,
            }
        )
    return {"conflicts": out}


@router.get("/health/summary")
async def health_summary(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> dict:
    """Per-source last-event-received time and 1h/24h ingestion counts --
    a stale last-seen is the "red flag" the spec's Pipeline Health view
    highlights."""
    now = utcnow()
    since_1h = now - timedelta(hours=1)
    since_24h = now - timedelta(hours=24)

    out = {}
    for source in IngestSourceSystem:
        if source == IngestSourceSystem.OMS:
            last_seen = await session.scalar(
                select(func.max(OrderVersion.created_at)).where(OrderVersion.provenance == source.value)
            )
            count_1h = await session.scalar(
                select(func.count()).where(OrderVersion.provenance == source.value, OrderVersion.created_at >= since_1h)
            )
            count_24h = await session.scalar(
                select(func.count()).where(OrderVersion.provenance == source.value, OrderVersion.created_at >= since_24h)
            )
        else:
            last_seen = await session.scalar(
                select(func.max(LogVersion.created_at)).where(LogVersion.provenance == source.value)
            )
            count_1h = await session.scalar(
                select(func.count()).where(LogVersion.provenance == source.value, LogVersion.created_at >= since_1h)
            )
            count_24h = await session.scalar(
                select(func.count()).where(LogVersion.provenance == source.value, LogVersion.created_at >= since_24h)
            )
        out[source.value] = {"last_seen": last_seen, "events_1h": count_1h or 0, "events_24h": count_24h or 0}

    dead_letter_count = await session.scalar(select(func.count()).select_from(DeadLetter))
    outbox_pending = await session.scalar(select(func.count()).where(Outbox.published.is_(False)))
    return {"sources": out, "dead_letter_count": dead_letter_count or 0, "outbox_pending_count": outbox_pending or 0}


@router.get("/dead-letters")
async def dead_letters(
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> dict:
    rows = list(await session.scalars(select(DeadLetter).order_by(DeadLetter.failed_at.desc()).limit(limit)))
    return {
        "dead_letters": [
            {"id": r.id, "raw_event": r.raw_event, "error_reason": r.error_reason, "attempt_count": r.attempt_count, "failed_at": r.failed_at}
            for r in rows
        ]
    }


@router.get("/outbox/pending-count")
async def outbox_pending_count(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> dict:
    pending = await session.scalar(select(func.count()).where(Outbox.published.is_(False)))
    total = await session.scalar(select(func.count()).select_from(Outbox))
    return {"pending_count": pending or 0, "total_count": total or 0}
