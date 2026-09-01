"""normalize() unit tests, one per adapter -- pure functions, no DB/event
loop needed. Each test exercises the specific raw-format quirk that
adapter's module docstring documents (per spec §2.1 / the testing
checklist)."""
from datetime import UTC, datetime

from app.ingest.adapters import cc_adapter, oms_adapter, payments_adapter, pos_adapter, returns_adapter, webapp_adapter, wms_adapter
from app.ingest.enums import IngestSourceSystem


def test_webapp_normalize_epoch_ms_and_user_id():
    event = webapp_adapter.normalize(
        {"user_id": "cust-1", "order_id": "ord-1", "event_type": "cart_abandoned", "ts_ms": 1735689600000, "tz": "America/New_York", "cart_value": 84.5}
    )
    assert event.customer_id == "cust-1"
    assert event.order_id == "ord-1"
    assert event.source_system == IngestSourceSystem.WEBAPP
    assert event.fact_type == "cart_abandoned"
    assert event.event_time == datetime.fromtimestamp(1735689600, tz=UTC)
    assert event.payload == {"cart_value": 84.5}


def test_pos_normalize_local_timezone_and_loyalty_id():
    event = pos_adapter.normalize(
        {"loyalty_id": "cust-1", "order_id": "ord-1", "store_id": "S-042", "amount": 49.99, "local_ts": "2026-08-15T14:30:00", "tz": "America/Chicago"}
    )
    assert event.customer_id == "cust-1"
    assert event.fact_type == "store_transaction"
    # 14:30 America/Chicago (UTC-5 in August, DST) == 19:30 UTC
    assert event.event_time.astimezone(UTC).hour == 19
    assert event.payload["amount"] == 49.99


def test_oms_normalize_abbreviated_field_names():
    event = oms_adapter.normalize(
        {"customer_id": "cust-1", "ord_id": "ord-1", "stat": "shipped", "event_ts": "2026-08-15T18:00:00Z", "tz": "UTC", "channel": "web"}
    )
    assert event.order_id == "ord-1"
    assert event.fact_type == "order_status"
    assert event.payload["status"] == "shipped"
    assert event.payload["channel"] == "web"


def test_wms_normalize_missing_customer_id_and_late_evidence():
    event = wms_adapter.normalize(
        {"order_id": "ord-1", "carrier": "UPS", "status": "delivered", "occurred_at": "2026-08-10T09:15:00Z", "tz": "UTC"}
    )
    assert event.customer_id is None  # WMS legitimately doesn't know the customer
    assert event.order_id == "ord-1"
    assert event.fact_type == "fulfilment_update"
    assert event.event_time < event.received_time  # the "late evidence" case


def test_payments_normalize_cents_and_epoch_seconds():
    event = payments_adapter.normalize(
        {"customer_id": "cust-1", "order_id": "ord-1", "amount_cents": 4999, "status": "captured", "ts": 1754038800, "tz": "UTC"}
    )
    assert event.fact_type == "payment_event"
    assert event.payload["amount"] == 49.99  # cents -> decimal dollars
    assert event.event_time == datetime.fromtimestamp(1754038800, tz=UTC)


def test_cc_normalize_linked_order_field():
    event = cc_adapter.normalize(
        {"customer_id": "cust-1", "linked_order": "ord-1", "channel": "phone", "disposition": "escalated", "transcript_summary": "disputes charge", "occurred_at": "2026-08-16T10:05:00Z", "tz": "UTC"}
    )
    assert event.order_id == "ord-1"
    assert event.fact_type == "contact_record"
    assert event.payload["transcript_summary"] == "disputes charge"


def test_returns_normalize_order_no_and_rma_fields():
    event = returns_adapter.normalize(
        {"customer_id": "cust-1", "order_no": "ord-1", "rma": "RMA-7734", "reason": "defective", "amount": 49.99, "occurred_at": "2026-08-20T12:00:00Z", "tz": "UTC"}
    )
    assert event.order_id == "ord-1"
    assert event.fact_type == "return_record"
    assert event.payload["rma"] == "RMA-7734"
