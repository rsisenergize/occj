"""Fulfilment / carrier (WMS) adapter.

Raw quirks handled: WMS/carrier events are commonly delivered well after
they actually happened (batched carrier scans, delayed webhooks) -- so
received_time (now, when this adapter got the webhook) can be
meaningfully later than event_time (`occurred_at`, when the scan actually
happened); both are preserved rather than collapsed into one timestamp.
customer_id is frequently absent -- WMS/carriers usually only know the
order/tracking id, not the customer -- so it's read from an optional
field and left None when missing; engine.py resolves the customer through
the order in that case (see engine._resolve_customer).

Example raw payload:
    {
      "order_id": "ord-5001",
      "carrier": "UPS",
      "tracking_number": "1Z999AA10123456784",
      "status": "delivered",
      "occurred_at": "2026-08-10T09:15:00Z",
      "tz": "UTC"
    }
"""
from app.db import utcnow
from app.ingest.adapters.base import build_webhook_router, parse_iso
from app.ingest.enums import IngestSourceSystem
from app.ingest.schemas import CanonicalEvent

SOURCE = IngestSourceSystem.WMS


def normalize(raw: dict) -> CanonicalEvent:
    payload = {k: v for k, v in raw.items() if k not in {"order_id", "customer_id", "occurred_at", "tz"}}
    return CanonicalEvent(
        customer_id=raw.get("customer_id"),
        order_id=raw["order_id"],
        event_time=parse_iso(raw["occurred_at"]),
        received_time=utcnow(),
        timezone=raw.get("tz", "UTC"),
        source_system=SOURCE,
        fact_type="fulfilment_update",
        payload=payload,
    )


router = build_webhook_router(source=SOURCE, path="/wms", normalize=normalize)
