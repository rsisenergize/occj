from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_roles
from app.db import get_session
from app.engine.case_service import get_or_create_customer, run_case_cycle
from app.models.auth import User
from app.models.case import Case
from app.models.enums import ActorType, CaseStatus, SourceType, UserRole
from app.reconciliation.reconciler import ingest_evidence
from app.schemas.common import ActionRequestOut, EvidenceIngest, EvidenceRecordOut

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

_OPEN_STATUSES = (
    CaseStatus.OPEN,
    CaseStatus.INVESTIGATING,
    CaseStatus.PENDING_EVIDENCE,
    CaseStatus.PENDING_APPROVAL,
    CaseStatus.ACTION_IN_PROGRESS,
    CaseStatus.PENDING_CUSTOMER_UPDATE,
    CaseStatus.REOPENED,
)


@router.post("/evidence")
async def ingest(
    body: EvidenceIngest,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_roles(UserRole.AGENT, UserRole.SUPERVISOR, UserRole.ADMIN)),
) -> dict:
    """Represents any of the 7 source systems (or a webhook from a real
    integration) delivering a new/corrected fact. Automatically reconciles,
    regenerates hypotheses, and drives the NBA loop for any open case tied
    to this customer -- evidence arriving is what makes the agent react,
    not a human pressing a button."""
    customer = await get_or_create_customer(
        session,
        external_customer_id=body.external_customer_id,
        display_name=body.customer_display_name,
        tier=body.customer_tier,
    )
    record = await ingest_evidence(
        session,
        customer=customer,
        source_type=SourceType(body.source_type),
        provenance_source=body.provenance_source,
        external_ref=body.external_ref,
        occurred_at=body.occurred_at,
        order_id=body.order_id,
        payload=body.payload,
        actor_type=ActorType.SYSTEM,
    )

    actions_taken = []
    if body.case_id:
        cases = [await session.get(Case, body.case_id)]
    else:
        cases = list(
            await session.scalars(
                select(Case).where(Case.customer_id == customer.id, Case.status.in_(_OPEN_STATUSES))
            )
        )
    for case in cases:
        if case is None:
            continue
        actions_taken.extend(await run_case_cycle(session, case))

    await session.commit()
    return {
        "evidence": EvidenceRecordOut.model_validate(record),
        "cases_updated": [c.id for c in cases if c is not None],
        "actions_taken": [ActionRequestOut.model_validate(a) for a in actions_taken],
    }
