"""Connector contract every tool (real or mock) implements.

Kept deliberately narrow: a connector receives the ActionRequest plus
whatever ancillary context the executor already looked up (case, customer,
a ticket id), and returns a ToolResult. It never touches the DB session
directly -- if executing it should also record new evidence (e.g. an ITSM
escalation that turns out to correlate with an existing incident), it
returns that as data (`evidence_to_ingest`) and the executor -- which owns
the session -- is what actually writes it. That keeps connectors trivially
unit-testable and keeps "what gets persisted" in one place.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.models.action import ActionRequest


@dataclass
class ToolResult:
    success: bool
    response_payload: dict = field(default_factory=dict)
    error_message: str | None = None
    # True when the primary effect succeeded but something secondary (e.g. a
    # confirmation notification) failed -- the case needing a human glance,
    # not a full retry of the primary effect.
    needs_manual_review: bool = False
    # Evidence records this execution surfaced or created, for the executor
    # to ingest via the reconciliation engine (source_type, provenance_source,
    # external_ref, occurred_at, payload, and optionally order_id -- the
    # same kwargs ingest_evidence takes, minus `customer`).
    evidence_to_ingest: list[dict] = field(default_factory=list)


class ConnectorError(Exception):
    """A connector-level failure that should count as a failed attempt
    (eligible for retry) rather than crash the executor."""


class Connector(ABC):
    name: str

    @abstractmethod
    async def execute(self, action: ActionRequest, context: dict, attempt_number: int) -> ToolResult: ...
