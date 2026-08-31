from app.models.enums import SourceType, UncertaintyFlagType
from app.reconciliation.reconciler import ingest_evidence, reconcile_case
from tests.conftest import ago, make_case, make_customer


async def test_correction_supersedes_without_losing_history(session, now):
    customer = await make_customer(session)
    await make_case(session, customer, order_id="ord-1")

    v1 = await ingest_evidence(
        session, customer=customer, source_type=SourceType.ORDER, provenance_source="mock:oms",
        external_ref="ord-1", occurred_at=ago(now, hours=1), order_id="ord-1",
        payload={"status": "confirmed", "amount": 100.0, "channel": "online"},
    )
    v2 = await ingest_evidence(
        session, customer=customer, source_type=SourceType.ORDER, provenance_source="mock:oms",
        external_ref="ord-1", occurred_at=ago(now, minutes=30), order_id="ord-1",
        payload={"status": "confirmed", "amount": 90.0, "channel": "online"},
    )

    assert v2.supersedes_id == v1.id
    assert v2.payload["amount"] == 90.0

    await session.refresh(v1)
    assert v1.is_superseded is True  # old fact preserved, just marked non-current


async def test_exact_repeat_delivery_is_not_a_new_fact(session, now):
    customer = await make_customer(session)
    payload = {"status": "confirmed", "amount": 100.0, "channel": "online"}

    first = await ingest_evidence(
        session, customer=customer, source_type=SourceType.ORDER, provenance_source="mock:oms",
        external_ref="ord-1", occurred_at=ago(now, hours=1), order_id="ord-1", payload=payload,
    )
    second = await ingest_evidence(
        session, customer=customer, source_type=SourceType.ORDER, provenance_source="mock:oms",
        external_ref="ord-1", occurred_at=ago(now, hours=1), order_id="ord-1", payload=payload,
    )
    assert second.id == first.id  # duplicate delivery resolves to the same canonical record


async def test_duplicate_charge_flag_is_scoped_per_order(session, now):
    """Two captured payments on two DIFFERENT orders are two legitimate
    purchases, not a duplicate charge -- regression test for a real bug
    found during manual end-to-end testing."""
    customer = await make_customer(session)
    case = await make_case(session, customer)

    for i in range(2):
        await ingest_evidence(
            session, customer=customer, source_type=SourceType.ORDER, provenance_source="mock:oms",
            external_ref=f"ord-{i}", occurred_at=ago(now, hours=2), order_id=f"ord-{i}",
            payload={"status": "confirmed", "amount": 50.0, "channel": "online"},
        )
        await ingest_evidence(
            session, customer=customer, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
            external_ref=f"pay-{i}", occurred_at=ago(now, hours=2), order_id=f"ord-{i}",
            payload={"status": "captured", "amount": 50.0, "method": "card"},
        )

    _, flags = await reconcile_case(session, case)
    assert not any(f.flag_type == UncertaintyFlagType.DUPLICATE for f in flags)


async def test_duplicate_charge_flag_fires_for_same_order(session, now):
    customer = await make_customer(session)
    case = await make_case(session, customer, order_id="ord-1")
    await ingest_evidence(
        session, customer=customer, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
        external_ref="pay-a", occurred_at=ago(now, hours=2), order_id="ord-1",
        payload={"status": "captured", "amount": 50.0, "method": "card"},
    )
    await ingest_evidence(
        session, customer=customer, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
        external_ref="pay-b", occurred_at=ago(now, hours=2), order_id="ord-1",
        payload={"status": "captured", "amount": 50.0, "method": "card"},
    )
    _, flags = await reconcile_case(session, case)
    assert any(f.flag_type == UncertaintyFlagType.DUPLICATE for f in flags)


async def test_missing_followup_flag_only_after_sla_window(session, now):
    customer = await make_customer(session)
    case = await make_case(session, customer, order_id="ord-1")
    await ingest_evidence(
        session, customer=customer, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
        external_ref="pay-1", occurred_at=ago(now, hours=1), order_id="ord-1",
        payload={"status": "captured", "amount": 50.0, "method": "card"},
    )
    _, flags = await reconcile_case(session, case)
    assert not any(f.flag_type == UncertaintyFlagType.MISSING for f in flags)  # still within 48h window

    # Same payment, but recorded 3 days ago -- now overdue.
    customer2 = await make_customer(session, external_customer_id="cust-2")
    case2 = await make_case(session, customer2, order_id="ord-2")
    await ingest_evidence(
        session, customer=customer2, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
        external_ref="pay-2", occurred_at=ago(now, days=3), order_id="ord-2",
        payload={"status": "captured", "amount": 50.0, "method": "card"},
    )
    _, flags2 = await reconcile_case(session, case2)
    assert any(f.flag_type == UncertaintyFlagType.MISSING for f in flags2)
