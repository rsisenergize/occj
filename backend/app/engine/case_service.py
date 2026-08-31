"""Case-level orchestration used by the API layer: creating a case,
reacting to newly ingested evidence, and driving the pipeline forward until
it naturally stalls (an approval gate, evidence that hasn't arrived, or the
case closes). This is what makes the system feel agentic end-to-end without
a human clicking "next" at every one of the 9 stages -- it only ever stops
where the design says a human belongs.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record as record_audit
from app.db import utcnow
from app.engine.hypothesis_engine import generate_or_update_hypotheses
from app.engine.orchestrator import advance_case
from app.models.action import ActionRequest
from app.models.case import Case, Customer
from app.models.enums import ActionStatus, ActorType, CaseTriggerType
from app.reconciliation.reconciler import reconcile_case

MAX_AUTO_STEPS = 12
STALLING_STATUSES = {
    ActionStatus.PENDING_APPROVAL,
    ActionStatus.NEEDS_MANUAL_REVIEW,
    ActionStatus.FAILED,
}


async def get_or_create_customer(
    session: AsyncSession, *, external_customer_id: str, display_name: str, tier: str = "standard",
    email: str | None = None, phone: str | None = None,
) -> Customer:
    customer = await session.scalar(select(Customer).where(Customer.external_customer_id == external_customer_id))
    if customer is not None:
        return customer
    customer = Customer(
        external_customer_id=external_customer_id, display_name=display_name, tier=tier, email=email, phone=phone
    )
    session.add(customer)
    await session.flush()
    return customer


async def create_case(
    session: AsyncSession,
    *,
    customer: Customer,
    trigger_type: CaseTriggerType,
    opened_by_user_id: str | None = None,
    order_id: str | None = None,
    summary: str | None = None,
) -> Case:
    case = Case(
        customer_id=customer.id,
        order_id=order_id,
        trigger_type=trigger_type,
        opened_by_user_id=opened_by_user_id,
        summary=summary,
        last_activity_at=utcnow(),
    )
    session.add(case)
    await session.flush()
    await record_audit(
        session,
        case_id=case.id,
        entity_type="case",
        entity_id=case.id,
        event="opened",
        actor_type=ActorType.HUMAN_DECISION if opened_by_user_id else ActorType.SYSTEM,
        actor_id=opened_by_user_id or "system",
        payload={"trigger_type": trigger_type.value, "customer_id": customer.id, "order_id": order_id},
    )
    return case


async def run_case_cycle(session: AsyncSession, case: Case) -> list[ActionRequest]:
    """Reconcile, (re)generate hypotheses, then drive the NBA loop until it
    stalls. Call this after any evidence tied to an open case changes."""
    await reconcile_case(session, case)
    await generate_or_update_hypotheses(session, case)

    taken: list[ActionRequest] = []
    for _ in range(MAX_AUTO_STEPS):
        action = await advance_case(session, case)
        if action is None:
            break
        taken.append(action)
        if action.status in STALLING_STATUSES:
            break
        if taken.count(action) > 1:  # safety: same object returned twice means truly stuck
            break
    return taken
