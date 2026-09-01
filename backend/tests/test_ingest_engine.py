"""Integration tests for the Reconciliation Engine (app.ingest.engine),
against the same in-memory-SQLite `session` fixture the rest of the suite
uses. Covers customer/timeline/order resolution, append-only version
writes with conflict detection wired end-to-end, the WMS
identity-via-order case, the unresolvable-identity error path, and outbox
transaction atomicity."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.ingest import engine
from app.ingest.enums import IngestSourceSystem
from app.ingest.models import Conflict, IngestOrder, Log, LogVersion, Outbox, OrderVersion, Timeline
from app.ingest.schemas import CanonicalEvent
from app.models.case import Customer


def _event(**overrides) -> CanonicalEvent:
    defaults = dict(
        customer_id="cust-1",
        order_id="ord-1",
        event_time=datetime(2026, 8, 1, tzinfo=UTC),
        received_time=datetime(2026, 8, 1, 0, 0, 5, tzinfo=UTC),
        timezone="UTC",
        source_system=IngestSourceSystem.OMS,
        fact_type="order_status",
        payload={"status": "placed"},
    )
    defaults.update(overrides)
    return CanonicalEvent(**defaults)


async def test_first_event_creates_customer_timeline_order_and_version(session):
    await engine.handle_event(session, _event())
    await session.commit()

    customer = await session.scalar(select(Customer).where(Customer.external_customer_id == "cust-1"))
    assert customer is not None
    timeline = await session.scalar(select(Timeline).where(Timeline.customer_id == customer.id))
    assert timeline is not None
    order = await session.scalar(select(IngestOrder).where(IngestOrder.order_ref == "ord-1"))
    assert order is not None
    version = await session.scalar(select(OrderVersion).where(OrderVersion.order_id == order.id))
    assert version.version_no == 1
    assert version.status == "placed"

    outbox_rows = list(await session.scalars(select(Outbox).where(Outbox.aggregate_id == timeline.id)))
    assert [o.event_type for o in outbox_rows] == ["order.updated"]  # no conflict row, first version


async def test_second_open_timeline_is_reused_not_recreated(session):
    await engine.handle_event(session, _event())
    await engine.handle_event(session, _event(fact_type="payment_event", payload={"status": "captured", "amount": 10.0}))
    await session.commit()

    customer = await session.scalar(select(Customer).where(Customer.external_customer_id == "cust-1"))
    timelines = list(await session.scalars(select(Timeline).where(Timeline.customer_id == customer.id)))
    assert len(timelines) == 1  # both events reused the same open timeline


async def test_order_status_progression_writes_versions_without_conflict(session):
    await engine.handle_event(session, _event(payload={"status": "placed"}))
    await engine.handle_event(session, _event(payload={"status": "shipped"}))
    await session.commit()

    order = await session.scalar(select(IngestOrder).where(IngestOrder.order_ref == "ord-1"))
    versions = list(await session.scalars(select(OrderVersion).where(OrderVersion.order_id == order.id).order_by(OrderVersion.version_no)))
    assert [v.status for v in versions] == ["placed", "shipped"]
    assert await session.scalar(select(Conflict)) is None


async def test_payment_amount_conflict_is_detected_and_auto_resolved(session):
    await engine.handle_event(session, _event(source_system=IngestSourceSystem.PAYMENTS, fact_type="payment_event", payload={"status": "captured", "amount": 49.99}))
    await engine.handle_event(session, _event(source_system=IngestSourceSystem.PAYMENTS, fact_type="payment_event", payload={"status": "captured", "amount": 59.99}))
    await session.commit()

    conflict = await session.scalar(select(Conflict))
    assert conflict is not None
    assert conflict.fact_type == "payment_event"
    assert conflict.resolution_status.value == "resolved"
    assert conflict.resolution_rule == "trusted_source_precedence"

    # both versions retained -- never deleted
    log = await session.scalar(select(Log).where(Log.fact_type == "payment_event"))
    versions = list(await session.scalars(select(LogVersion).where(LogVersion.log_id == log.id)))
    assert len(versions) == 2


async def test_wms_event_with_no_customer_id_resolves_via_existing_order(session):
    await engine.handle_event(session, _event())  # establishes the order under cust-1
    await engine.handle_event(
        session,
        _event(customer_id=None, source_system=IngestSourceSystem.WMS, fact_type="fulfilment_update", payload={"status": "delivered"}),
    )
    await session.commit()

    log = await session.scalar(select(Log).where(Log.fact_type == "fulfilment_update"))
    assert log is not None
    customer = await session.scalar(select(Customer).where(Customer.external_customer_id == "cust-1"))
    assert log.customer_id == customer.id  # resolved through the order, not a null/second customer


async def test_unresolvable_identity_raises(session):
    with pytest.raises(engine.UnresolvableIdentityError):
        await engine.handle_event(
            session,
            _event(customer_id=None, order_id="ord-never-seen", source_system=IngestSourceSystem.WMS, fact_type="fulfilment_update", payload={"status": "delivered"}),
        )


async def test_outbox_write_is_atomic_with_the_version_it_describes(session, monkeypatch):
    """Simulates failure mid-transaction (spec's outbox-atomicity test):
    everything handle_event flushed for the SECOND event -- the new
    LogVersion, the Conflict, its ConflictReferences, and the Outbox rows
    -- must roll back together when a later step in that same call fails."""
    await engine.handle_event(session, _event(source_system=IngestSourceSystem.PAYMENTS, fact_type="payment_event", payload={"status": "captured", "amount": 49.99}))
    await session.commit()

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated failure after version + conflict writes, before outbox commit")

    monkeypatch.setattr(engine, "_write_outbox", boom)

    with pytest.raises(RuntimeError):
        await engine.handle_event(
            session,
            _event(source_system=IngestSourceSystem.PAYMENTS, fact_type="payment_event", payload={"status": "captured", "amount": 59.99}),
        )
    await session.rollback()

    log = await session.scalar(select(Log).where(Log.fact_type == "payment_event"))
    versions = list(await session.scalars(select(LogVersion).where(LogVersion.log_id == log.id)))
    assert len(versions) == 1  # the second version's flush was rolled back, not left partially committed
    assert await session.scalar(select(Conflict)) is None  # the conflict it would have raised never persisted either
