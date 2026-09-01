"""Payment gateway adapter.

Raw quirks handled: amounts arrive in integer cents (`amount_cents`)
rather than a decimal currency amount, and timestamps are epoch-*seconds*
(`ts`), not milliseconds like the web/app adapter. normalize() converts
both into this pipeline's canonical conventions (decimal `amount` in the
payload, an absolute UTC event_time) so nothing downstream ever has to
know which source it came from to interpret a value correctly.

Example raw payload:
    {
      "customer_id": "cust-1001",
      "order_id": "ord-5001",
      "amount_cents": 4999,
      "status": "captured",
      "method": "card",
      "ts": 1735689600,
      "tz": "UTC"
    }
"""
from datetime import UTC, datetime

from app.db import utcnow
from app.ingest.adapters.base import build_webhook_router
from app.ingest.enums import IngestSourceSystem
from app.ingest.schemas import CanonicalEvent

SOURCE = IngestSourceSystem.PAYMENTS


def normalize(raw: dict) -> CanonicalEvent:
    event_time = datetime.fromtimestamp(raw["ts"], tz=UTC)
    payload = {k: v for k, v in raw.items() if k not in {"customer_id", "order_id", "amount_cents", "ts", "tz"}}
    payload["amount"] = round(raw.get("amount_cents", 0) / 100.0, 2)
    return CanonicalEvent(
        customer_id=raw.get("customer_id"),
        order_id=raw.get("order_id"),
        event_time=event_time,
        received_time=utcnow(),
        timezone=raw.get("tz", "UTC"),
        source_system=SOURCE,
        fact_type="payment_event",
        payload=payload,
    )


router = build_webhook_router(source=SOURCE, path="/payments", normalize=normalize)
