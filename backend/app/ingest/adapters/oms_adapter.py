"""Order Management System (OMS) adapter.

Raw quirks handled: order id and status arrive under the abbreviated field
names `ord_id`/`stat` rather than `order_id`/`status`. fact_type is always
"order_status" -- this is the one source whose facts write to
OrderVersion (see engine.py's ORDER_STATUS_FACT_TYPE), not LogVersion.

Example raw payload:
    {
      "customer_id": "cust-1001",
      "ord_id": "ord-5001",
      "stat": "shipped",
      "event_ts": "2026-08-15T18:00:00Z",
      "tz": "UTC",
      "channel": "web"
    }
"""
from app.db import utcnow
from app.ingest.adapters.base import build_webhook_router, parse_iso
from app.ingest.enums import IngestSourceSystem
from app.ingest.schemas import CanonicalEvent

SOURCE = IngestSourceSystem.OMS


def normalize(raw: dict) -> CanonicalEvent:
    payload = {"status": raw["stat"]}
    payload.update({k: v for k, v in raw.items() if k not in {"customer_id", "ord_id", "stat", "event_ts", "tz"}})
    return CanonicalEvent(
        customer_id=raw.get("customer_id"),
        order_id=raw["ord_id"],
        event_time=parse_iso(raw["event_ts"]),
        received_time=utcnow(),
        timezone=raw.get("tz", "UTC"),
        source_system=SOURCE,
        fact_type="order_status",
        payload=payload,
    )


router = build_webhook_router(source=SOURCE, path="/oms", normalize=normalize)
