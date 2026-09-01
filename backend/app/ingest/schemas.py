"""The canonical normalized event envelope every adapter must produce
before publishing to the EventStreamer -- exactly the shape specified in
the module spec §2, as a Pydantic model so adapters get validation for
free and the streamer/engine never see a malformed envelope."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.ingest.enums import IngestSourceSystem


class CanonicalEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    customer_id: str | None = None
    order_id: str | None = None
    event_time: datetime  # when it actually happened
    received_time: datetime  # when our adapter ingested it
    timezone: str  # IANA tz string, e.g. "America/New_York"
    source_system: IngestSourceSystem
    fact_type: str
    payload: dict[str, Any]
