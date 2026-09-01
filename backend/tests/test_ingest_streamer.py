"""EventStreamer unit tests: retry-then-dead-letter, multi-subscriber
fan-out, and source_system filtering. No DB -- a stub dead_letter_sink
captures calls instead."""
import asyncio
from datetime import UTC, datetime

import pytest

from app.ingest.enums import IngestSourceSystem
from app.ingest.schemas import CanonicalEvent
from app.ingest.streamer import EventStreamer


def _event(source_system: IngestSourceSystem = IngestSourceSystem.OMS) -> CanonicalEvent:
    return CanonicalEvent(
        customer_id="cust-1",
        order_id="ord-1",
        event_time=datetime(2026, 8, 1, tzinfo=UTC),
        received_time=datetime(2026, 8, 1, tzinfo=UTC),
        timezone="UTC",
        source_system=source_system,
        fact_type="order_status",
        payload={"status": "placed"},
    )


async def _drain(streamer: EventStreamer, *subs) -> None:
    # let the background consumer task(s) actually run
    for _ in range(10):
        await asyncio.sleep(0)
    await asyncio.sleep(1.2)  # covers MAX_RETRIES backoff (0.1 + 0.5s) with headroom


async def test_handler_failure_retries_then_dead_letters():
    dead_letters: list[tuple] = []

    async def sink(event, error_reason, attempt_count):
        dead_letters.append((event, error_reason, attempt_count))

    call_count = 0

    async def always_fails(event: CanonicalEvent) -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("handler always fails")

    streamer = EventStreamer(dead_letter_sink=sink)
    streamer.subscribe(always_fails, name="always-fails")
    await streamer.publish(_event())
    await _drain(streamer)
    await streamer.shutdown()

    assert call_count == 3  # MAX_RETRIES
    assert len(dead_letters) == 1
    assert dead_letters[0][2] == 3
    assert "always fails" in dead_letters[0][1]


async def test_handler_succeeding_on_retry_never_dead_letters():
    attempts = []

    async def fails_once_then_succeeds(event: CanonicalEvent) -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise ValueError("transient")

    dead_letters = []

    async def sink(*args):
        dead_letters.append(args)

    streamer = EventStreamer(dead_letter_sink=sink)
    streamer.subscribe(fails_once_then_succeeds, name="flaky")
    await streamer.publish(_event())
    await _drain(streamer)
    await streamer.shutdown()

    assert len(attempts) == 2
    assert dead_letters == []


async def test_multiple_subscribers_each_see_every_matching_event():
    """The fan-out requirement: Reconciliation Engine now, Audit/Projector
    later -- both must independently receive the same event, not compete
    for it."""
    received_a: list[CanonicalEvent] = []
    received_b: list[CanonicalEvent] = []

    async def handler_a(event: CanonicalEvent) -> None:
        received_a.append(event)

    async def handler_b(event: CanonicalEvent) -> None:
        received_b.append(event)

    streamer = EventStreamer()
    streamer.subscribe(handler_a, name="a")
    streamer.subscribe(handler_b, name="b")
    await streamer.publish(_event())
    await _drain(streamer)
    await streamer.shutdown()

    assert len(received_a) == 1
    assert len(received_b) == 1


async def test_source_system_filter_excludes_non_matching_events():
    received: list[CanonicalEvent] = []

    async def handler(event: CanonicalEvent) -> None:
        received.append(event)

    streamer = EventStreamer()
    streamer.subscribe(handler, source_systems={"oms"}, name="oms-only")
    await streamer.publish(_event(source_system=IngestSourceSystem.PAYMENTS))
    await streamer.publish(_event(source_system=IngestSourceSystem.OMS))
    await _drain(streamer)
    await streamer.shutdown()

    assert len(received) == 1
    assert received[0].source_system == IngestSourceSystem.OMS
