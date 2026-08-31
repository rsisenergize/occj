"""Ingestion, dedup/correction handling, canonical timeline assembly, and
explicit uncertainty detection.

This module is the "assemble and reconcile ... into a coherent, time-aware
operating view" and "detect missing, stale, duplicated or contradictory
information" capabilities from the brief. It intentionally does not decide
what to *do* about uncertainty -- that's the NBA engine's job, reading the
UncertaintyFlag rows this module produces.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record as record_audit
from app.config import get_settings
from app.db import ensure_aware, utcnow
from app.engine.stage import advance_stage
from app.models.canonical import CanonicalEvent, UncertaintyFlag
from app.models.case import Case, Customer
from app.models.enums import ActorType, JourneyStage, SourceType, UncertaintyFlagType
from app.models.evidence import EvidenceRecord
from app.reconciliation.rules import (
    DISPUTE_DISPOSITIONS,
    EXPECTED_FOLLOWUPS,
    FULFILLMENT_TERMINAL_STATUSES,
)

settings = get_settings()


async def ingest_evidence(
    session: AsyncSession,
    *,
    customer: Customer,
    source_type: SourceType,
    provenance_source: str,
    external_ref: str,
    occurred_at: datetime,
    payload: dict,
    order_id: str | None = None,
    recorded_at_source: datetime | None = None,
    actor_type: ActorType = ActorType.SYSTEM,
) -> EvidenceRecord:
    """Idempotent ingestion: new fact, exact-repeat delivery (duplicate), or a
    correction (same external ref, different payload) -- never overwritten,
    never silently duplicated as a new "current" fact."""
    existing = await session.scalar(
        select(EvidenceRecord).where(
            EvidenceRecord.source_type == source_type,
            EvidenceRecord.external_ref == external_ref,
            EvidenceRecord.provenance_source == provenance_source,
            EvidenceRecord.is_superseded.is_(False),
        )
    )
    now = utcnow()

    if existing is not None and existing.payload == payload:
        dup = EvidenceRecord(
            customer_id=customer.id,
            order_id=order_id,
            source_type=source_type,
            external_ref=external_ref,
            provenance_source=provenance_source,
            occurred_at=occurred_at,
            recorded_at_source=recorded_at_source,
            ingested_at=now,
            payload=payload,
            actor_type=actor_type,
            is_duplicate_of=existing.id,
        )
        session.add(dup)
        await session.flush()
        await record_audit(
            session,
            case_id=None,
            entity_type="evidence_record",
            entity_id=dup.id,
            event="duplicate_delivery_ingested",
            actor_type=ActorType.SYSTEM,
            actor_id=provenance_source,
            payload={"duplicate_of": existing.id, "external_ref": external_ref},
        )
        return existing

    record_kwargs = dict(
        customer_id=customer.id,
        order_id=order_id,
        source_type=source_type,
        external_ref=external_ref,
        provenance_source=provenance_source,
        occurred_at=occurred_at,
        recorded_at_source=recorded_at_source,
        ingested_at=now,
        payload=payload,
        actor_type=actor_type,
    )

    if existing is not None:
        existing.is_superseded = True
        new_record = EvidenceRecord(**record_kwargs, supersedes_id=existing.id)
        session.add(new_record)
        await session.flush()
        await record_audit(
            session,
            case_id=None,
            entity_type="evidence_record",
            entity_id=new_record.id,
            event="correction_ingested",
            actor_type=actor_type,
            actor_id=provenance_source,
            payload={
                "supersedes": existing.id,
                "previous_payload": existing.payload,
                "new_payload": payload,
            },
        )
        return new_record

    new_record = EvidenceRecord(**record_kwargs)
    session.add(new_record)
    await session.flush()
    await record_audit(
        session,
        case_id=None,
        entity_type="evidence_record",
        entity_id=new_record.id,
        event="ingested",
        actor_type=actor_type,
        actor_id=provenance_source,
        payload={"source_type": source_type.value, "external_ref": external_ref},
    )
    return new_record


async def _current_evidence_for_case(session: AsyncSession, case: Case) -> list[EvidenceRecord]:
    conditions = [
        EvidenceRecord.customer_id == case.customer_id,
        EvidenceRecord.is_superseded.is_(False),
        EvidenceRecord.is_duplicate_of.is_(None),
    ]
    result = await session.scalars(
        select(EvidenceRecord).where(*conditions).order_by(EvidenceRecord.occurred_at)
    )
    return list(result)


async def assemble_timeline(session: AsyncSession, case: Case) -> list[CanonicalEvent]:
    """Ensure every current EvidenceRecord for this case's customer has a
    corresponding CanonicalEvent, and that corrected records update the
    existing entry rather than creating a duplicate one."""
    evidence = await _current_evidence_for_case(session, case)

    existing_events = await session.scalars(
        select(CanonicalEvent).where(CanonicalEvent.case_id == case.id)
    )
    by_evidence_id = {e.evidence_record_id: e for e in existing_events}
    # Also index by the chain root so a correction's new evidence_record_id
    # still maps onto the same timeline entry as the record it superseded.
    superseded_chain: dict[str, str] = {}
    for rec in evidence:
        if rec.supersedes_id:
            superseded_chain[rec.supersedes_id] = rec.id

    timeline: list[CanonicalEvent] = []
    for rec in evidence:
        event = by_evidence_id.get(rec.id)
        if event is None:
            # was this evidence record's predecessor already a canonical event?
            # (walk back through supersedes chain to find it)
            predecessor_id = rec.supersedes_id
            while predecessor_id and event is None:
                event = by_evidence_id.get(predecessor_id)
                if event:
                    break
                predecessor_id = None  # only one hop stored; good enough for this scope
        if event is None:
            event = CanonicalEvent(
                case_id=case.id,
                evidence_record_id=rec.id,
                source_type=rec.source_type,
                effective_at=rec.occurred_at,
                summary=_summarize(rec),
            )
            session.add(event)
        else:
            event.evidence_record_id = rec.id
            event.effective_at = rec.occurred_at
            event.summary = _summarize(rec)
        timeline.append(event)

    await session.flush()
    timeline.sort(key=lambda e: e.effective_at)
    return timeline


def _summarize(rec: EvidenceRecord) -> str:
    p = rec.payload or {}
    match rec.source_type:
        case SourceType.WEB_APP_EVENT:
            return f"Web/app event: {p.get('event', 'unknown')}"
        case SourceType.STORE_TRANSACTION:
            return f"Store transaction ({p.get('transaction_type', 'sale')}): ${p.get('amount', '?')}"
        case SourceType.ORDER:
            return f"Order {p.get('status', 'unknown')} via {p.get('channel', 'unknown')}: ${p.get('amount', '?')}"
        case SourceType.FULFILLMENT_UPDATE:
            return f"Fulfillment: {p.get('status', 'unknown')} ({p.get('carrier', 'unknown')})"
        case SourceType.PAYMENT:
            return f"Payment {p.get('status', 'unknown')}: ${p.get('amount', '?')} via {p.get('method', 'unknown')}"
        case SourceType.CONTACT_CENTER_RECORD:
            return f"Contact ({p.get('channel', 'unknown')}): {p.get('subject', 'no subject')}"
        case SourceType.RETURN:
            return f"Return {p.get('status', 'unknown')}: ${p.get('amount', '?')} ({p.get('reason', 'unspecified')})"
        case SourceType.ITSM_INCIDENT:
            return f"ITSM incident [{p.get('severity', 'unknown')}]: {p.get('title', 'untitled')}"
        case _:
            return "Evidence recorded"


async def detect_uncertainty(session: AsyncSession, case: Case) -> list[UncertaintyFlag]:
    """Raise explicit, queryable flags for missing/stale/duplicate/
    contradictory evidence. Never silently resolved -- callers decide what
    (if anything) to do about an open flag."""
    evidence = await _current_evidence_for_case(session, case)
    now = utcnow()
    new_flags: list[UncertaintyFlag] = []

    already_flagged = await session.scalars(
        select(UncertaintyFlag).where(
            UncertaintyFlag.case_id == case.id,
            UncertaintyFlag.resolved_at.is_(None),
        )
    )
    open_descriptions = {f.description for f in already_flagged}

    def add_flag(flag_type: UncertaintyFlagType, related_ids: list[str], description: str) -> None:
        if description in open_descriptions:
            return
        new_flags.append(
            UncertaintyFlag(
                case_id=case.id,
                flag_type=flag_type,
                related_evidence_ids=related_ids,
                description=description,
                detected_at=now,
            )
        )
        open_descriptions.add(description)

    by_source: dict[SourceType, list[EvidenceRecord]] = {}
    for rec in evidence:
        by_source.setdefault(rec.source_type, []).append(rec)

    # --- Duplicate business events (e.g. two payment captures for one order) ---
    # Scoped per order_id: two captured payments for *different* orders are
    # two legitimate purchases, not a duplicate charge.
    payments = by_source.get(SourceType.PAYMENT, [])
    captured_by_order: dict[str | None, list[EvidenceRecord]] = {}
    for p in payments:
        if (p.payload or {}).get("status") == "captured":
            captured_by_order.setdefault(p.order_id, []).append(p)
    for order_id, captured in captured_by_order.items():
        if len(captured) > 1:
            add_flag(
                UncertaintyFlagType.DUPLICATE,
                [p.id for p in captured],
                f"{len(captured)} captured payments recorded for order {order_id} -- possible duplicate charge.",
            )

    # --- Contradictory fulfillment terminal statuses (scoped per order_id --
    # different orders legitimately having different outcomes is not a
    # contradiction) ---
    fulfillments = by_source.get(SourceType.FULFILLMENT_UPDATE, [])
    fulfillments_by_order: dict[str | None, list[EvidenceRecord]] = {}
    for f in fulfillments:
        fulfillments_by_order.setdefault(f.order_id, []).append(f)
    for order_id, order_fulfillments in fulfillments_by_order.items():
        terminal = [f for f in order_fulfillments if (f.payload or {}).get("status") in FULFILLMENT_TERMINAL_STATUSES]
        distinct_terminal_statuses = {(f.payload or {}).get("status") for f in terminal}
        if len(distinct_terminal_statuses) > 1:
            add_flag(
                UncertaintyFlagType.CONTRADICTORY,
                [f.id for f in terminal],
                f"Conflicting fulfillment outcomes recorded for order {order_id}: {sorted(distinct_terminal_statuses)}.",
            )

    # --- Contact-centre dispute contradicting a "delivered" fulfillment record (same order) ---
    contacts = by_source.get(SourceType.CONTACT_CENTER_RECORD, [])
    disputes_by_order: dict[str | None, list[EvidenceRecord]] = {}
    for c in contacts:
        if (c.payload or {}).get("disposition") in DISPUTE_DISPOSITIONS:
            disputes_by_order.setdefault(c.order_id, []).append(c)
    for order_id, disputes in disputes_by_order.items():
        delivered = [f for f in fulfillments_by_order.get(order_id, []) if (f.payload or {}).get("status") == "delivered"]
        if disputes and delivered:
            add_flag(
                UncertaintyFlagType.CONTRADICTORY,
                [d.id for d in disputes] + [f.id for f in delivered],
                f"Customer disputes receipt of order {order_id} but fulfillment records show delivered.",
            )

    # --- Missing expected follow-up evidence ---
    for rec in evidence:
        followup = EXPECTED_FOLLOWUPS.get(rec.source_type)
        if not followup:
            continue
        expected_type, window = followup
        deadline = ensure_aware(rec.occurred_at) + window
        if now <= deadline:
            continue  # still within the SLA window
        has_followup = any(
            f.source_type == expected_type
            and f.order_id == rec.order_id
            and ensure_aware(f.occurred_at) >= ensure_aware(rec.occurred_at)
            for f in evidence
        )
        if not has_followup:
            add_flag(
                UncertaintyFlagType.MISSING,
                [rec.id],
                f"Expected {expected_type.value} after {rec.source_type.value} "
                f"({rec.external_ref}) has not arrived within {window}.",
            )

    # --- Stale evidence: still-open evidence with no activity in a long time ---
    if evidence:
        most_recent = max(ensure_aware(e.occurred_at) for e in evidence)
        stale_cutoff = now - settings_stale_delta()
        if most_recent < stale_cutoff:
            add_flag(
                UncertaintyFlagType.STALE,
                [e.id for e in evidence if ensure_aware(e.occurred_at) == most_recent],
                f"No new evidence for this case since {most_recent.isoformat()} "
                f"(older than the {settings.stale_evidence_hours}h staleness threshold).",
            )

    for flag in new_flags:
        session.add(flag)
    if new_flags:
        await session.flush()
        for flag in new_flags:
            await record_audit(
                session,
                case_id=case.id,
                entity_type="uncertainty_flag",
                entity_id=flag.id,
                event="raised",
                actor_type=ActorType.SYSTEM,
                actor_id="reconciliation_engine",
                payload={"flag_type": flag.flag_type.value, "description": flag.description},
            )
    return new_flags


def settings_stale_delta():
    from datetime import timedelta

    return timedelta(hours=settings.stale_evidence_hours)


async def reconcile_case(session: AsyncSession, case: Case) -> tuple[list[CanonicalEvent], list[UncertaintyFlag]]:
    """Top-level entry point: assemble the timeline, then detect uncertainty
    against the freshly-assembled evidence set. Called after any evidence
    ingestion that's linked to this case, and by the periodic sweep."""
    timeline = await assemble_timeline(session, case)
    flags = await detect_uncertainty(session, case)
    if timeline:
        advance_stage(case, JourneyStage.JOURNEY_ASSEMBLED)
    case.last_activity_at = utcnow()
    await session.flush()
    return timeline, flags
