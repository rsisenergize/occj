"""Next-best-action engine.

Deterministic and explainable by design -- every branch below is a plain
if/elif over case state, deadlines, evidence gaps, and the recovery
catalog's own approval flags. This is intentional: the brief calls for
audit replay ("reviewers can reconstruct ... why it acted"), which is only
possible if the decision procedure is inspectable code, not a model call.
The LLM only ever writes the human-readable `rationale` text attached to
whatever this engine already decided.

One case advances by (at most) one live ActionRequest at a time -- a
`decide_next_action` call is a no-op while one is still in flight, which is
what prevents duplicate requests/actions when the engine is invoked more
than once for the same state (e.g. a retried API call, a re-triggered sweep).
"""
import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record as record_audit
from app.config import get_settings
from app.db import utcnow
from app.engine.impact_engine import assess_impact
from app.engine.recovery_catalog import rank_recovery_options
from app.models.action import ActionRequest, Approval
from app.models.canonical import UncertaintyFlag
from app.models.case import Case
from app.models.enums import (
    ActionStatus,
    ActionType,
    ActorType,
    ApprovalStatus,
    HypothesisStatus,
    SourceType,
    UncertaintyFlagType,
)
from app.models.evidence import EvidenceRecord
from app.models.hypothesis import Hypothesis
from app.models.impact import ImpactAssessment

settings = get_settings()

LIVE_STATUSES = (
    ActionStatus.PROPOSED,
    ActionStatus.PENDING_APPROVAL,
    ActionStatus.APPROVED,
    ActionStatus.EXECUTING,
)

# Hypothesis categories where a customer's individual complaint might
# actually be one symptom of a wider internal incident -- worth checking
# with ITSM before assuming this is a one-off.
SYSTEMIC_PRONE_CATEGORIES = {
    "order_confirmed_fulfillment_never_started",
    "wrong_address_or_failed_delivery_attempt",
    "fulfillment_shows_delivered_customer_disputes_receipt",
    "payment_captured_order_not_created",
}

CONFIDENCE_ACTION_THRESHOLD = 0.6


def _idempotency_key(case_id: str, action_type: ActionType, discriminator: str) -> str:
    raw = f"{case_id}:{action_type.value}:{discriminator}"
    return hashlib.sha256(raw.encode()).hexdigest()[:48]


async def _live_action(session: AsyncSession, case: Case) -> ActionRequest | None:
    return await session.scalar(
        select(ActionRequest).where(ActionRequest.case_id == case.id, ActionRequest.status.in_(LIVE_STATUSES))
    )


async def _actions_of_type(session: AsyncSession, case: Case, action_type: ActionType) -> list[ActionRequest]:
    return list(
        await session.scalars(
            select(ActionRequest).where(ActionRequest.case_id == case.id, ActionRequest.action_type == action_type)
        )
    )


async def _open_flags(session: AsyncSession, case: Case) -> list[UncertaintyFlag]:
    return list(
        await session.scalars(
            select(UncertaintyFlag).where(UncertaintyFlag.case_id == case.id, UncertaintyFlag.resolved_at.is_(None))
        )
    )


async def _propose(
    session: AsyncSession,
    case: Case,
    *,
    action_type: ActionType,
    target: dict,
    rationale: str,
    expected_value: float,
    requires_approval: bool,
    idempotency_discriminator: str,
    approval_role: str | None = None,
) -> ActionRequest:
    key = _idempotency_key(case.id, action_type, idempotency_discriminator)
    existing = await session.scalar(select(ActionRequest).where(ActionRequest.idempotency_key == key))
    if existing is not None:
        return existing  # identical decision already made -- never duplicate it

    status = ActionStatus.PENDING_APPROVAL if requires_approval else ActionStatus.PROPOSED
    action = ActionRequest(
        case_id=case.id,
        action_type=action_type,
        target=target,
        rationale=rationale,
        expected_value=expected_value,
        status=status,
        requires_approval=requires_approval,
        idempotency_key=key,
    )
    session.add(action)
    await session.flush()

    if requires_approval:
        session.add(
            Approval(
                action_request_id=action.id,
                required_role=approval_role or "supervisor",
                status=ApprovalStatus.PENDING,
            )
        )
        await session.flush()

    await record_audit(
        session,
        case_id=case.id,
        entity_type="action_request",
        entity_id=action.id,
        event="proposed",
        actor_type=ActorType.SYSTEM,
        actor_id="nba_engine",
        payload={"action_type": action_type.value, "requires_approval": requires_approval, "target": target},
    )
    return action


async def decide_next_action(session: AsyncSession, case: Case) -> ActionRequest | None:
    live = await _live_action(session, case)
    if live is not None and not case.needs_reevaluation:
        return live

    if case.needs_reevaluation:
        if live is not None:
            await record_audit(
                session,
                case_id=case.id,
                entity_type="case",
                entity_id=case.id,
                event="reevaluation_deferred_action_in_flight",
                actor_type=ActorType.SYSTEM,
                actor_id="nba_engine",
                payload={"live_action_id": live.id},
            )
            return live
        case.needs_reevaluation = False
        await session.flush()

    hypothesis: Hypothesis | None = None
    if case.primary_hypothesis_id:
        hypothesis = await session.get(Hypothesis, case.primary_hypothesis_id)

    # 1. No grounded hypothesis at all -- generic evidence request.
    if hypothesis is None or hypothesis.status != HypothesisStatus.ACTIVE:
        return await _propose(
            session,
            case,
            action_type=ActionType.REQUEST_EVIDENCE,
            target={"reason": "no_active_hypothesis"},
            rationale="No evidence-grounded, currently-active hypothesis yet -- requesting broader evidence before proceeding.",
            expected_value=0.1,
            requires_approval=False,
            idempotency_discriminator="generic",
        )

    # 2. Confidence too low and there's a specific gap to close -- targeted evidence request.
    open_flags = await _open_flags(session, case)
    missing_flags = [f for f in open_flags if f.flag_type == UncertaintyFlagType.MISSING]
    if hypothesis.confidence < CONFIDENCE_ACTION_THRESHOLD and missing_flags:
        flag = missing_flags[0]
        return await _propose(
            session,
            case,
            action_type=ActionType.REQUEST_EVIDENCE,
            target={"flag_id": flag.id, "description": flag.description},
            rationale=(
                f"Leading hypothesis '{hypothesis.category}' is at {hypothesis.confidence:.0%} confidence, "
                f"below the {CONFIDENCE_ACTION_THRESHOLD:.0%} action threshold. Requesting the missing evidence "
                f"most likely to move it: {flag.description}"
            ),
            expected_value=round((CONFIDENCE_ACTION_THRESHOLD - hypothesis.confidence) * 10, 2),
            requires_approval=False,
            idempotency_discriminator=flag.id,
        )

    # 3. Confidence sufficient -- assess impact if not already done for this hypothesis.
    impact = await session.scalar(
        select(ImpactAssessment)
        .where(ImpactAssessment.hypothesis_id == hypothesis.id)
        .order_by(ImpactAssessment.computed_at.desc())
    )
    if impact is None:
        action = await _propose(
            session,
            case,
            action_type=ActionType.RUN_ANALYSIS,
            target={"type": "impact_assessment", "hypothesis_id": hypothesis.id},
            rationale=(
                f"Hypothesis '{hypothesis.category}' reached {hypothesis.confidence:.0%} confidence -- "
                "assessing financial/SLA/customer-tier impact before selecting a recovery option."
            ),
            expected_value=hypothesis.confidence,
            requires_approval=False,
            idempotency_discriminator=hypothesis.id,
        )
        # Pure internal computation, no external side effects or retries
        # needed -- run it inline rather than round-tripping through the
        # tool-execution layer built for connectors with real failure modes.
        impact = await assess_impact(session, case, hypothesis)
        action.status = ActionStatus.SUCCEEDED
        action.decided_at = utcnow()
        await session.flush()
        return action

    # 4. Check whether this looks systemic before spending money on an individual remedy.
    itsm_actions = await _actions_of_type(session, case, ActionType.ESCALATE_ITSM)
    has_itsm_evidence = await session.scalar(
        select(EvidenceRecord).where(
            EvidenceRecord.customer_id == case.customer_id,
            EvidenceRecord.source_type == SourceType.ITSM_INCIDENT,
            EvidenceRecord.is_superseded.is_(False),
        )
    )
    if hypothesis.category in SYSTEMIC_PRONE_CATEGORIES and not itsm_actions and not has_itsm_evidence:
        return await _propose(
            session,
            case,
            action_type=ActionType.ESCALATE_ITSM,
            target={"hypothesis_id": hypothesis.id, "category": hypothesis.category},
            rationale=(
                f"'{hypothesis.category}' can be a symptom of a wider internal incident. Checking/raising an "
                "ITSM ticket before committing to an individual-customer remedy, so a systemic cause isn't "
                "handled one refund at a time."
            ),
            expected_value=impact.composite_score * 0.5,
            requires_approval=False,
            idempotency_discriminator=hypothesis.id,
        )

    # 5. Recovery: propose the best-ranked option not yet rejected.
    recovery_actions = await _actions_of_type(session, case, ActionType.EXECUTE_RECOVERY)
    rejected_codes = {
        a.target.get("option_code")
        for a in recovery_actions
        if a.status in (ActionStatus.REJECTED, ActionStatus.FAILED)
    }
    already_live_or_done = any(
        a.status in LIVE_STATUSES or a.status == ActionStatus.SUCCEEDED for a in recovery_actions
    )
    if not already_live_or_done:
        options = rank_recovery_options(hypothesis.category, impact.financial_exposure_usd, "")
        substantive = [o for o in options if o.code != "apology_status_update" and o.code not in rejected_codes]
        chosen = substantive[0] if substantive else next((o for o in options if o.code not in rejected_codes), None)
        if chosen is None:
            await record_audit(
                session,
                case_id=case.id,
                entity_type="case",
                entity_id=case.id,
                event="recovery_options_exhausted",
                actor_type=ActorType.SYSTEM,
                actor_id="nba_engine",
                payload={"hypothesis_id": hypothesis.id, "rejected_codes": sorted(rejected_codes)},
            )
            return None
        return await _propose(
            session,
            case,
            action_type=ActionType.EXECUTE_RECOVERY,
            target={
                "option_code": chosen.code,
                "label": chosen.label,
                "estimated_cost_usd": chosen.estimated_cost_usd,
                "hypothesis_id": hypothesis.id,
            },
            rationale=f"{chosen.rationale} Estimated cost: ${chosen.estimated_cost_usd:.2f}.",
            expected_value=impact.composite_score,
            requires_approval=chosen.requires_approval,
            approval_role=chosen.approval_role,
            idempotency_discriminator=f"{hypothesis.id}:{chosen.code}",
        )

    # 6. Recovery executed -- notify the customer, once.
    recovery_done = next((a for a in recovery_actions if a.status == ActionStatus.SUCCEEDED), None)
    notify_actions = await _actions_of_type(session, case, ActionType.NOTIFY_CUSTOMER)
    if recovery_done and not notify_actions:
        return await _propose(
            session,
            case,
            action_type=ActionType.NOTIFY_CUSTOMER,
            target={"recovery_action_id": recovery_done.id},
            rationale="Recovery action succeeded -- drafting and sending the customer a status update.",
            expected_value=impact.composite_score * 0.3,
            requires_approval=False,
            idempotency_discriminator=recovery_done.id,
        )

    # 7. Customer notified -- close the case.
    notify_done = next((a for a in notify_actions if a.status == ActionStatus.SUCCEEDED), None)
    close_actions = await _actions_of_type(session, case, ActionType.CLOSE_CASE)
    if notify_done and not close_actions:
        return await _propose(
            session,
            case,
            action_type=ActionType.CLOSE_CASE,
            target={"hypothesis_id": hypothesis.id},
            rationale="Customer notified of the resolved outcome -- closing the case with a full evidence/action summary retained.",
            expected_value=0.0,
            requires_approval=False,
            idempotency_discriminator=hypothesis.id,
        )

    return None
