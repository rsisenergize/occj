"""In-process, in-memory pub/sub -- the Kafka stand-in for this iteration.

[LIMITATION: no durability without Kafka.] Every event lives only in an
asyncio.Queue in this process's memory. If the process crashes between
publish() and a subscriber consuming the event, that event is lost -- there
is no write-ahead log, no persisted offset, nothing to replay from. This is
a deliberate, explicitly-scoped trade-off for this iteration, not an
oversight: see README.md's "Ingestion pipeline v2" section, and the
`Swap-in point for Kafka` note below for exactly what would change.

Design choice -- fan-out per subscriber, not one shared queue per
source_system: the spec offered "one queue per source_system, or a single
queue with fact_type routing" as the two options, but neither actually
satisfies "must support multiple consumers subscribing to the same stream
... WITHOUT tight coupling" (Reconciliation Engine now, Audit/Projector
later) -- a single queue shared by multiple consumers is a *competing*-
consumers pattern (one item goes to exactly one taker), not fan-out (every
subscriber sees every matching event). So: each subscribe() call gets its
own asyncio.Queue and its own background consumer task; publish() enqueues
onto every subscriber whose source_system filter matches. This is also the
shape that maps cleanly onto Kafka consumer groups later (each subscriber
becomes its own consumer group on the relevant topic(s)).

Swap-in point for Kafka: anything holding an `EventStreamer` only ever
calls `.publish(event)` and `.subscribe(handler, source_systems=...)` --
see the EventBus protocol below. A future KafkaEventBus implementing the
same two methods (publish -> produce, subscribe -> consumer-group loop)
drops in without touching adapters/ or engine.py.
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.ingest.schemas import CanonicalEvent

logger = logging.getLogger(__name__)

Handler = Callable[[CanonicalEvent], Awaitable[None]]
DeadLetterSink = Callable[[CanonicalEvent, str, int], Awaitable[None]]

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = [0.1, 0.5]  # between attempts 1->2 and 2->3
SUBSCRIBER_QUEUE_MAXSIZE = 1000


class EventBus(Protocol):
    """The swap-in interface -- see module docstring."""

    async def publish(self, event: CanonicalEvent) -> None: ...

    def subscribe(
        self, handler: Handler, *, source_systems: set[str] | None = None, name: str = ""
    ) -> None: ...


@dataclass
class _Subscriber:
    name: str
    handler: Handler
    source_systems: set[str] | None  # None = all
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAXSIZE))
    task: asyncio.Task | None = None


class EventStreamer:
    """In-process pub/sub implementing EventBus. publish() never blocks on a
    subscriber's processing -- it only enqueues (or dead-letters
    immediately if that subscriber's queue is full), so an adapter's
    webhook handler calling publish() can return 202 without waiting on
    reconciliation."""

    def __init__(self, *, dead_letter_sink: DeadLetterSink | None = None):
        self._subscribers: list[_Subscriber] = []
        self._dead_letter_sink = dead_letter_sink

    def subscribe(
        self, handler: Handler, *, source_systems: set[str] | None = None, name: str = ""
    ) -> None:
        """Register a new independent consumer. Must be called after an
        event loop is running (e.g. from app startup) -- it starts a
        background task that owns this subscriber's queue for the life of
        the process."""
        sub = _Subscriber(name=name or handler.__name__, handler=handler, source_systems=source_systems)
        sub.task = asyncio.create_task(self._consume(sub), name=f"streamer-subscriber-{sub.name}")
        self._subscribers.append(sub)
        logger.info("EventStreamer: subscriber '%s' registered (source_systems=%s)", sub.name, source_systems or "all")

    async def publish(self, event: CanonicalEvent) -> None:
        for sub in self._subscribers:
            if sub.source_systems is not None and event.source_system.value not in sub.source_systems:
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.error("EventStreamer: subscriber '%s' queue full, dead-lettering immediately", sub.name)
                await self._dead_letter(event, f"subscriber '{sub.name}' queue full", attempt_count=0)

    async def _consume(self, sub: _Subscriber) -> None:
        while True:
            event = await sub.queue.get()
            try:
                await self._deliver(sub, event)
            finally:
                sub.queue.task_done()

    async def _deliver(self, sub: _Subscriber, event: CanonicalEvent) -> None:
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await sub.handler(event)
                return
            except Exception as exc:  # noqa: BLE001 -- must never crash the streamer
                last_error = exc
                logger.warning(
                    "EventStreamer: subscriber '%s' handler failed (attempt %s/%s): %s",
                    sub.name, attempt, MAX_RETRIES, exc,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])
        await self._dead_letter(event, str(last_error), attempt_count=MAX_RETRIES)

    async def _dead_letter(self, event: CanonicalEvent, error_reason: str, attempt_count: int) -> None:
        if self._dead_letter_sink is None:
            logger.error("EventStreamer: no dead_letter_sink configured, dropping event: %s", error_reason)
            return
        await self._dead_letter_sink(event, error_reason, attempt_count)

    async def shutdown(self) -> None:
        """Cancel all subscriber consumer loops. Call from app shutdown --
        does not drain in-flight queue items (see the durability
        limitation above)."""
        for sub in self._subscribers:
            if sub.task is not None:
                sub.task.cancel()
        for sub in self._subscribers:
            if sub.task is not None:
                try:
                    await sub.task
                except asyncio.CancelledError:
                    pass
