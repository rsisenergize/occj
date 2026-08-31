from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user, require_roles
from app.db import get_session
from app.engine.case_service import create_case, get_or_create_customer, run_case_cycle
from app.models.action import ActionRequest
from app.models.auth import User
from app.models.canonical import CanonicalEvent, UncertaintyFlag
from app.models.case import Case, Customer
from app.models.enums import CaseTriggerType, UserRole
from app.models.hypothesis import EvidenceLink, Hypothesis
from app.models.impact import ImpactAssessment
from app.schemas.common import (
    ActionRequestOut,
    CaseCreate,
    CaseDetailOut,
    CaseOut,
    CanonicalEventOut,
    CustomerOut,
    EvidenceLinkOut,
    HypothesisOut,
    ImpactAssessmentOut,
    UncertaintyFlagOut,
)

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[CaseOut])
async def list_cases(
    status_filter: str | None = None,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list[Case]:
    query = select(Case).order_by(Case.created_at.desc())
    if status_filter:
        query = query.where(Case.status == status_filter)
    return list(await session.scalars(query))


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
async def open_case(
    body: CaseCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_roles(UserRole.AGENT, UserRole.SUPERVISOR)),
) -> Case:
    customer = await get_or_create_customer(
        session,
        external_customer_id=body.external_customer_id,
        display_name=body.customer_display_name,
        tier=body.customer_tier,
        email=body.customer_email,
        phone=body.customer_phone,
    )
    case = await create_case(
        session,
        customer=customer,
        trigger_type=CaseTriggerType.MANUAL,
        opened_by_user_id=user.id,
        order_id=body.order_id,
        summary=body.summary,
    )
    await run_case_cycle(session, case)
    await session.commit()
    await session.refresh(case)
    return case


async def _load_case_or_404(session: AsyncSession, case_id: str) -> Case:
    case = await session.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


@router.get("/{case_id}", response_model=CaseDetailOut)
async def get_case(
    case_id: str, session: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)
) -> CaseDetailOut:
    case = await _load_case_or_404(session, case_id)
    customer = await session.get(Customer, case.customer_id)

    timeline = list(
        await session.scalars(
            select(CanonicalEvent).where(CanonicalEvent.case_id == case.id).order_by(CanonicalEvent.effective_at)
        )
    )
    flags = list(
        await session.scalars(
            select(UncertaintyFlag).where(UncertaintyFlag.case_id == case.id).order_by(UncertaintyFlag.detected_at)
        )
    )
    hypotheses = list(
        await session.scalars(
            select(Hypothesis).where(Hypothesis.case_id == case.id).order_by(Hypothesis.created_at.desc())
        )
    )
    hyp_outs = []
    for h in hypotheses:
        links = list(await session.scalars(select(EvidenceLink).where(EvidenceLink.hypothesis_id == h.id)))
        hyp_outs.append(
            HypothesisOut(
                id=h.id,
                case_id=h.case_id,
                category=h.category,
                title=h.title,
                narrative=h.narrative,
                confidence=h.confidence,
                status=h.status.value,
                created_at=h.created_at,
                updated_at=h.updated_at,
                evidence_links=[EvidenceLinkOut.model_validate(link) for link in links],
            )
        )

    latest_impact = None
    if case.primary_hypothesis_id:
        latest_impact = await session.scalar(
            select(ImpactAssessment)
            .where(ImpactAssessment.hypothesis_id == case.primary_hypothesis_id)
            .order_by(ImpactAssessment.computed_at.desc())
        )

    actions = list(
        await session.scalars(
            select(ActionRequest).where(ActionRequest.case_id == case.id).order_by(ActionRequest.created_at)
        )
    )

    return CaseDetailOut(
        case=CaseOut.model_validate(case),
        customer=CustomerOut.model_validate(customer),
        timeline=[CanonicalEventOut.model_validate(e) for e in timeline],
        uncertainty_flags=[UncertaintyFlagOut.model_validate(f) for f in flags],
        hypotheses=hyp_outs,
        latest_impact=ImpactAssessmentOut.model_validate(latest_impact) if latest_impact else None,
        actions=[ActionRequestOut.model_validate(a) for a in actions],
    )


@router.post("/{case_id}/advance", response_model=list[ActionRequestOut])
async def advance(
    case_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_roles(UserRole.AGENT, UserRole.SUPERVISOR)),
) -> list[ActionRequest]:
    """Manually nudge the case forward -- normally happens automatically
    after evidence ingestion, but useful for demoing or unsticking a case
    once new evidence has been supplied through another channel."""
    case = await _load_case_or_404(session, case_id)
    actions = await run_case_cycle(session, case)
    await session.commit()
    return actions
