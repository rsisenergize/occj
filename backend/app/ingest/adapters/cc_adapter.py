"""Contact-centre (CCaaS) adapter.

Raw quirks handled: the order identifier arrives as `linked_order` rather
than `order_id`, and the meaningful content is a free-text transcript
summary rather than a structured status field -- preserved verbatim in
the payload for the investigator-facing side to read, not parsed further
here (no LLM/ML in this module).

Example raw payload:
    {
      "customer_id": "cust-1001",
      "linked_order": "ord-5001",
      "channel": "phone",
      "disposition": "escalated",
      "transcript_summary": "Customer disputes receiving the package; says tracking shows delivered but nothing arrived.",
      "occurred_at": "2026-08-16T10:05:00Z",
      "tz": "UTC"
    }
"""
from app.db import utcnow
from app.ingest.adapters.base import build_webhook_router, parse_iso
from app.ingest.enums import IngestSourceSystem
from app.ingest.schemas import CanonicalEvent

SOURCE = IngestSourceSystem.CC


def normalize(raw: dict) -> CanonicalEvent:
    payload = {k: v for k, v in raw.items() if k not in {"customer_id", "linked_order", "occurred_at", "tz"}}
    return CanonicalEvent(
        customer_id=raw.get("customer_id"),
        order_id=raw.get("linked_order"),
        event_time=parse_iso(raw["occurred_at"]),
        received_time=utcnow(),
        timezone=raw.get("tz", "UTC"),
        source_system=SOURCE,
        fact_type="contact_record",
        payload=payload,
    )


router = build_webhook_router(source=SOURCE, path="/cc", normalize=normalize)
