"""Audit replay: reconstruct case state at any point in time purely from
the append-only AuditEntry log -- what the brief calls "reviewers can
reconstruct what the system knew, why it acted, and what changed
afterward." No separate snapshot table; every relevant transition (stage
change, hypothesis creation, action lifecycle, approval decision) already
writes an audit entry as it happens (see stage.py, hypothesis_engine.py,
nba_engine.py, executor.py, approvals/service.py), so folding the log up to
a timestamp *is* the state as of that time.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.models.audit import AuditEntry
from app.models.enums import JourneyStage


async def get_case_audit_trail(
    session: AsyncSession, case_id: str, as_of: datetime | None = None
) -> list[AuditEntry]:
    query = select(AuditEntry).where(AuditEntry.case_id == case_id)
    if as_of is not None:
        query = query.where(AuditEntry.occurred_at <= as_of)
    query = query.order_by(AuditEntry.occurred_at, AuditEntry.created_at)
    return list(await session.scalars(query))


async def replay_case_state(session: AsyncSession, case_id: str, as_of: datetime | None = None) -> dict:
    entries = await get_case_audit_trail(session, case_id, as_of)

    stage = JourneyStage.ISSUE_REPORTED
    hypotheses: dict[str, dict] = {}
    actions: dict[str, dict] = {}
    approvals: dict[str, dict] = {}
    evidence_event_count = 0

    for entry in entries:
        if entry.entity_type == "case" and entry.event == "stage_advanced":
            stage = JourneyStage(entry.payload["to"])
        elif entry.entity_type == "case" and entry.event == "reevaluation_triggered":
            stage = JourneyStage.FAILURE_LOCATED
        elif entry.entity_type == "hypothesis" and entry.event == "created":
            hypotheses[entry.entity_id] = {
                "category": entry.payload.get("category"),
                "confidence": entry.payload.get("confidence"),
                "as_of_this_event": entry.occurred_at.isoformat(),
            }
        elif entry.entity_type == "action_request":
            record = actions.setdefault(entry.entity_id, {"history": []})
            record["last_event"] = entry.event
            record["updated_at"] = entry.occurred_at.isoformat()
            record["history"].append({"event": entry.event, "at": entry.occurred_at.isoformat(), "payload": entry.payload})
        elif entry.entity_type == "approval":
            approvals[entry.entity_id] = {
                "event": entry.event,
                "at": entry.occurred_at.isoformat(),
                "actor_id": entry.actor_id,
            }
        elif entry.entity_type == "evidence_record":
            evidence_event_count += 1

    return {
        "case_id": case_id,
        "as_of": (as_of or utcnow()).isoformat(),
        "stage": stage.value,
        "hypotheses_known_at_this_point": hypotheses,
        "actions_known_at_this_point": actions,
        "approvals_known_at_this_point": approvals,
        "evidence_events_count": evidence_event_count,
        "audit_entry_count": len(entries),
        "trail": [
            {
                "occurred_at": e.occurred_at.isoformat(),
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "event": e.event,
                "actor_type": e.actor_type.value,
                "actor_id": e.actor_id,
                "payload": e.payload,
            }
            for e in entries
        ],
    }
