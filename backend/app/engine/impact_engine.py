"""Explainable impact scoring: financial exposure + SLA-breach risk +
customer-tier weight -> one composite urgency/expected-value number, with
every component stored so the audit trail and UI can show why, not just
the number."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record as record_audit
from app.db import ensure_aware, utcnow
from app.models.canonical import UncertaintyFlag
from app.models.case import Case, Customer
from app.models.enums import ActorType, UncertaintyFlagType
from app.models.evidence import EvidenceRecord
from app.models.hypothesis import EvidenceLink, Hypothesis
from app.models.impact import ImpactAssessment

TIER_WEIGHT = {"standard": 1.0, "silver": 1.15, "gold": 1.3, "platinum": 1.5}


async def _hypothesis_evidence(session: AsyncSession, hypothesis: Hypothesis) -> list[EvidenceRecord]:
    links = list(
        await session.scalars(select(EvidenceLink).where(EvidenceLink.hypothesis_id == hypothesis.id))
    )
    if not links:
        return []
    records = list(
        await session.scalars(
            select(EvidenceRecord).where(EvidenceRecord.id.in_([link.evidence_record_id for link in links]))
        )
    )
    return records


async def _order_evidence(session: AsyncSession, customer_id: str, order_ids: set[str]) -> list[EvidenceRecord]:
    """The hypothesis's own cited evidence is often a fulfillment/contact
    record with no dollar figure on it at all (e.g. "delivered" vs. "item
    not received") -- the actual amount at risk lives on that order's
    ORDER/PAYMENT/RETURN/STORE_TRANSACTION records. Pull those in too so
    exposure reflects the real transaction value, not just whatever
    happened to be cited."""
    order_ids = {o for o in order_ids if o}
    if not order_ids:
        return []
    return list(
        await session.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.customer_id == customer_id,
                EvidenceRecord.order_id.in_(order_ids),
                EvidenceRecord.is_superseded.is_(False),
            )
        )
    )


async def assess_impact(session: AsyncSession, case: Case, hypothesis: Hypothesis) -> ImpactAssessment:
    cited_evidence = await _hypothesis_evidence(session, hypothesis)
    order_ids = {rec.order_id for rec in cited_evidence} | ({case.order_id} if case.order_id else set())
    order_evidence = await _order_evidence(session, case.customer_id, order_ids)
    evidence = {rec.id: rec for rec in cited_evidence + order_evidence}.values()

    # Financial exposure: the largest dollar figure implicated by the cited
    # evidence AND the order(s) it concerns (a duplicate charge's extra
    # amount, an at-risk order/refund amount, ...). Simple and explainable
    # rather than a fragile sum that could double-count the same order from
    # multiple angles.
    amounts = [float(rec.payload.get("amount", 0) or 0) for rec in evidence if isinstance(rec.payload, dict)]
    financial_exposure = max(amounts) if amounts else 0.0

    # SLA breach risk: how overdue the worst open MISSING flag tied to this
    # case is, as a 0..1 ratio (capped at 1 = at least 2x its own window
    # overdue). No open MISSING flag -> 0 risk from this component.
    now = utcnow()
    open_missing = list(
        await session.scalars(
            select(UncertaintyFlag).where(
                UncertaintyFlag.case_id == case.id,
                UncertaintyFlag.flag_type == UncertaintyFlagType.MISSING,
                UncertaintyFlag.resolved_at.is_(None),
            )
        )
    )
    sla_breach_score = 0.0
    if open_missing:
        oldest_detected = min(ensure_aware(f.detected_at) for f in open_missing)
        overdue_hours = max(0.0, (now - oldest_detected).total_seconds() / 3600.0)
        sla_breach_score = min(1.0, overdue_hours / 24.0)

    customer = await session.get(Customer, case.customer_id)
    tier = customer.tier if customer else "standard"
    tier_weight = TIER_WEIGHT.get(tier, 1.0)

    composite = round(financial_exposure * tier_weight * (1.0 + sla_breach_score), 2)

    assessment = ImpactAssessment(
        case_id=case.id,
        hypothesis_id=hypothesis.id,
        financial_exposure_usd=financial_exposure,
        sla_breach_score=round(sla_breach_score, 4),
        customer_tier_weight=tier_weight,
        composite_score=composite,
        explanation={
            "financial_exposure_usd": financial_exposure,
            "sla_breach_score": round(sla_breach_score, 4),
            "customer_tier": tier,
            "customer_tier_weight": tier_weight,
            "formula": "composite = financial_exposure_usd * tier_weight * (1 + sla_breach_score)",
            "open_missing_flags": len(open_missing),
        },
        computed_at=now,
    )
    session.add(assessment)
    await session.flush()

    await record_audit(
        session,
        case_id=case.id,
        entity_type="impact_assessment",
        entity_id=assessment.id,
        event="computed",
        actor_type=ActorType.SYSTEM,
        actor_id="impact_engine",
        payload=assessment.explanation,
    )
    return assessment
