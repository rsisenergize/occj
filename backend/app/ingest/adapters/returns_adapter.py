"""Returns system adapter.

Raw quirks handled: the order identifier arrives as `order_no` rather
than `order_id`, and the return-merchandise-authorization number
(`rma`) is a returns-specific identifier preserved in the payload.

Example raw payload:
    {
      "customer_id": "cust-1001",
      "order_no": "ord-5001",
      "rma": "RMA-7734",
      "reason": "defective",
      "amount": 49.99,
      "occurred_at": "2026-08-20T12:00:00Z",
      "tz": "UTC"
    }
"""
from app.db import utcnow
from app.ingest.adapters.base import build_webhook_router, parse_iso
from app.ingest.enums import IngestSourceSystem
from app.ingest.schemas import CanonicalEvent

SOURCE = IngestSourceSystem.RETURNS


def normalize(raw: dict) -> CanonicalEvent:
    payload = {k: v for k, v in raw.items() if k not in {"customer_id", "order_no", "occurred_at", "tz"}}
    return CanonicalEvent(
        customer_id=raw.get("customer_id"),
        order_id=raw.get("order_no"),
        event_time=parse_iso(raw["occurred_at"]),
        received_time=utcnow(),
        timezone=raw.get("tz", "UTC"),
        source_system=SOURCE,
        fact_type="return_record",
        payload=payload,
    )


router = build_webhook_router(source=SOURCE, path="/returns", normalize=normalize)
