"""Append-only audit writer. Every other module that changes state calls
`record` instead of writing AuditEntry rows itself, so the audit trail's
shape stays consistent no matter which engine produced the change."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.models.audit import AuditEntry
from app.models.enums import ActorType


async def record(
    session: AsyncSession,
    *,
    case_id: str | None,
    entity_type: str,
    entity_id: str,
    event: str,
    actor_type: ActorType,
    actor_id: str | None = None,
    payload: dict | None = None,
) -> AuditEntry:
    entry = AuditEntry(
        case_id=case_id,
        entity_type=entity_type,
        entity_id=entity_id,
        event=event,
        actor_type=actor_type,
        actor_id=actor_id,
        payload=payload or {},
        occurred_at=utcnow(),
    )
    session.add(entry)
    await session.flush()
    return entry
