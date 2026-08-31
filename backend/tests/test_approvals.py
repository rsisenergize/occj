import pytest

from app.approvals.service import ApprovalError, decide_approval
from app.models.action import ActionRequest, Approval
from app.models.auth import User
from app.models.enums import ActionStatus, ActionType, ApprovalStatus, UserRole
from tests.conftest import make_case, make_customer


async def _make_pending_approval(session, case, role: str) -> tuple[ActionRequest, Approval]:
    action = ActionRequest(
        case_id=case.id, action_type=ActionType.EXECUTE_RECOVERY, target={}, rationale="test",
        expected_value=1.0, status=ActionStatus.PENDING_APPROVAL, requires_approval=True,
        idempotency_key=f"appr-test-{role}",
    )
    session.add(action)
    await session.flush()
    approval = Approval(action_request_id=action.id, required_role=role, status=ApprovalStatus.PENDING)
    session.add(approval)
    await session.flush()
    return action, approval


async def test_wrong_role_cannot_approve(session, now):
    customer = await make_customer(session)
    case = await make_case(session, customer)
    action, approval = await _make_pending_approval(session, case, "finance_approver")
    agent = User(username="agent-test", password_hash="x", role=UserRole.AGENT, display_name="Agent")
    session.add(agent)
    await session.flush()

    with pytest.raises(ApprovalError):
        await decide_approval(session, approval, decision=ApprovalStatus.APPROVED, user=agent)

    await session.refresh(approval)
    assert approval.status == ApprovalStatus.PENDING  # unchanged


async def test_matching_role_can_approve(session, now):
    customer = await make_customer(session)
    case = await make_case(session, customer)
    action, approval = await _make_pending_approval(session, case, "finance_approver")
    finance = User(username="finance-test", password_hash="x", role=UserRole.FINANCE_APPROVER, display_name="Finance")
    session.add(finance)
    await session.flush()

    await decide_approval(session, approval, decision=ApprovalStatus.APPROVED, user=finance)
    await session.refresh(approval)
    await session.refresh(action)
    assert approval.status == ApprovalStatus.APPROVED
    assert action.status == ActionStatus.APPROVED


async def test_admin_can_approve_any_role(session, now):
    customer = await make_customer(session)
    case = await make_case(session, customer)
    action, approval = await _make_pending_approval(session, case, "supervisor")
    admin = User(username="admin-test", password_hash="x", role=UserRole.ADMIN, display_name="Admin")
    session.add(admin)
    await session.flush()

    await decide_approval(session, approval, decision=ApprovalStatus.APPROVED, user=admin)
    await session.refresh(approval)
    assert approval.status == ApprovalStatus.APPROVED


async def test_cannot_decide_an_already_decided_approval(session, now):
    customer = await make_customer(session)
    case = await make_case(session, customer)
    action, approval = await _make_pending_approval(session, case, "supervisor")
    supervisor = User(username="sup-test2", password_hash="x", role=UserRole.SUPERVISOR, display_name="Sup")
    session.add(supervisor)
    await session.flush()

    await decide_approval(session, approval, decision=ApprovalStatus.APPROVED, user=supervisor)
    with pytest.raises(ApprovalError):
        await decide_approval(session, approval, decision=ApprovalStatus.REJECTED, user=supervisor)
