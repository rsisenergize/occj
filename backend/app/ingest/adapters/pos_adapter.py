"""In-store POS adapter.

Raw quirks handled: timestamps are in the store's *local* time with no UTC
offset (`local_ts`, paired with a separate `tz` field) rather than an
absolute instant, and the customer identifier arrives as `loyalty_id`.

Example raw payload:
    {
      "loyalty_id": "cust-1001",
      "order_id": "ord-5001",
      "store_id": "S-042",
      "amount": 49.99,
      "local_ts": "2026-08-15T14:30:00",
      "tz": "America/Chicago"
    }
"""
from datetime import UTC
from zoneinfo import ZoneInfo

from app.db import utcnow
from app.ingest.adapters.base import build_webhook_router, parse_iso
from app.ingest.enums import IngestSourceSystem
from app.ingest.schemas import CanonicalEvent

SOURCE = IngestSourceSystem.POS


def normalize(raw: dict) -> CanonicalEvent:
    tz_name = raw.get("tz", "UTC")
    naive = parse_iso(raw["local_ts"]).replace(tzinfo=None)
    event_time = naive.replace(tzinfo=ZoneInfo(tz_name)).astimezone(UTC)
    payload = {k: v for k, v in raw.items() if k not in {"loyalty_id", "order_id", "local_ts", "tz"}}
    return CanonicalEvent(
        customer_id=raw.get("loyalty_id"),
        order_id=raw.get("order_id"),
        event_time=event_time,
        received_time=utcnow(),
        timezone=tz_name,
        source_system=SOURCE,
        fact_type="store_transaction",
        payload=payload,
    )


router = build_webhook_router(source=SOURCE, path="/pos", normalize=normalize)
