"""Wires the Reconciliation Engine (engine.handle_event) and the dead-letter
sink onto a real DB session lifecycle, and holds the process-wide
EventStreamer singleton. Kept separate from engine.py so engine.py itself
stays a pure function of (session, event) -- easy to unit test without an
event loop or a streamer."""
import logging

from app.db import AsyncSessionLocal
from app.ingest.engine import handle_event
from app.ingest.models import DeadLetter
from app.ingest.schemas import CanonicalEvent
from app.ingest.streamer import EventStreamer

logger = logging.getLogger(__name__)


async def reconciliation_handler(event: CanonicalEvent) -> None:
    """One DB transaction per event: commit on success, rollback and
    re-raise on failure so the streamer's own retry/dead-letter logic
    handles it uniformly."""
    async with AsyncSessionLocal() as session:
        try:
            await handle_event(session, event)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def write_dead_letter(event: CanonicalEvent, error_reason: str, attempt_count: int) -> None:
    async with AsyncSessionLocal() as session:
        session.add(
            DeadLetter(
                raw_event=event.model_dump(mode="json"),
                error_reason=error_reason[:1024],
                attempt_count=attempt_count,
            )
        )
        await session.commit()
    logger.error("Ingest event dead-lettered after %s attempts: %s", attempt_count, error_reason)


streamer = EventStreamer(dead_letter_sink=write_dead_letter)


def start_reconciliation_subscriber() -> None:
    """Call once at app startup (inside the running event loop -- see
    main.py's lifespan). Idempotent to call more than once is NOT
    guaranteed; callers must only call this once per process."""
    streamer.subscribe(reconciliation_handler, name="reconciliation_engine")
