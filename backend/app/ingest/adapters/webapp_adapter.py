"""Web/App analytics adapter.

Raw quirks handled: epoch-millisecond timestamps (`ts_ms`), and the
customer identifier arriving as `user_id` rather than `customer_id`.
fact_type is taken from the raw event itself (`event_type`) since web/app
analytics emit many distinct event kinds (cart_abandoned, page_view,
checkout_started, ...), unlike e.g. OMS which only ever reports one kind.

Example raw payload:
    {
      "user_id": "cust-1001",
      "order_id": "ord-5001",           # optional -- not every webapp event is order-linked
      "event_type": "cart_abandoned",
      "ts_ms": 1735689600000,
      "tz": "America/New_York",
      "session_id": "sess-abc123",
      "cart_value": 84.50
    }
"""
from datetime import UTC, datetime

from app.db import utcnow
from app.ingest.adapters.base import build_webhook_router
from app.ingest.enums import IngestSourceSystem
from app.ingest.schemas import CanonicalEvent

SOURCE = IngestSourceSystem.WEBAPP


def normalize(raw: dict) -> CanonicalEvent:
    event_time = datetime.fromtimestamp(raw["ts_ms"] / 1000, tz=UTC)
    payload = {k: v for k, v in raw.items() if k not in {"user_id", "order_id", "event_type", "ts_ms", "tz"}}
    return CanonicalEvent(
        customer_id=raw.get("user_id"),
        order_id=raw.get("order_id"),
        event_time=event_time,
        received_time=utcnow(),
        timezone=raw.get("tz", "UTC"),
        source_system=SOURCE,
        fact_type=raw.get("event_type", "webapp_event"),
        payload=payload,
    )


router = build_webhook_router(source=SOURCE, path="/webapp", normalize=normalize)
