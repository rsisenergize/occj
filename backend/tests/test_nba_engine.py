from sqlalchemy import select

from app.approvals.service import decide_approval
from app.engine.case_service import run_case_cycle
from app.engine.nba_engine import decide_next_action
from app.models.action import ActionRequest, Approval
from app.models.auth import User
from app.models.enums import ActionType, ApprovalStatus, SourceType, UserRole
from app.reconciliation.reconciler import ingest_evidence
from tests.conftest import ago, make_case, make_customer


async def test_full_pipeline_reaches_closure(session, now):
    """The end-to-end scenario verified manually during development,
    codified: evidence -> hypothesis -> impact -> ITSM escalation ->
    approval-gated recovery -> customer notification -> case closure."""
    customer = await make_customer(session, tier="standard")
    case = await make_case(session, customer, order_id="ord-1")

    for i in range(2):
        await ingest_evidence(
            session, customer=customer, source_type=SourceType.ORDER, provenance_source="mock:oms",
            external_ref=f"ord-{i}", occurred_at=ago(now, days=4), order_id=f"ord-{i}",
            payload={"status": "confirmed", "amount": 250.0, "channel": "online"},
        )
        await ingest_evidence(
            session, customer=customer, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
            external_ref=f"pay-{i}", occurred_at=ago(now, days=4), order_id=f"ord-{i}",
            payload={"status": "captured", "amount": 250.0, "method": "card"},
        )

    supervisor = User(username="sup-test", password_hash="x", role=UserRole.SUPERVISOR, display_name="Sup")
    session.add(supervisor)
    await session.flush()

    await run_case_cycle(session, case)
    for _ in range(5):
        pending = await session.scalar(select(Approval).where(Approval.status == ApprovalStatus.PENDING))
        if pending is None:
            break
        await decide_approval(session, pending, decision=ApprovalStatus.APPROVED, user=supervisor)
        await run_case_cycle(session, case)

    assert case.status == "closed"
    assert case.stage == "outcome_retained"
    assert case.closed_at is not None

    action_types = {
        a.action_type
        for a in await session.scalars(select(ActionRequest).where(ActionRequest.case_id == case.id))
    }
    assert ActionType.ESCALATE_ITSM in action_types
    assert ActionType.EXECUTE_RECOVERY in action_types
    assert ActionType.NOTIFY_CUSTOMER in action_types
    assert ActionType.CLOSE_CASE in action_types


async def test_decide_next_action_is_idempotent_while_action_is_live(session, now):
    customer = await make_customer(session)
    case = await make_case(session, customer, order_id="ord-1")
    await ingest_evidence(
        session, customer=customer, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
        external_ref="pay-a", occurred_at=ago(now, hours=1), order_id="ord-1",
        payload={"status": "captured", "amount": 50.0, "method": "card"},
    )
    await run_case_cycle(session, case)

    first = await decide_next_action(session, case)
    second = await decide_next_action(session, case)
    assert first is not None
    assert first.id == second.id  # same live action returned, never duplicated
