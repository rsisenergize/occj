"""Applies a human approval/rejection decision to an ActionRequest.

Authorization (does this user's role match what the action actually needs)
is checked here, not just at the API layer, so any future caller of this
service gets the same guarantee -- a supervisor cannot approve a
finance_approver-gated action just because they found a way to call this
function directly.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record as record_audit
from app.db import utcnow
from app.models.action import ActionRequest, Approval
from app.models.auth import User
from app.models.enums import ActionStatus, ActorType, ApprovalStatus, UserRole


class ApprovalError(Exception):
    pass


async def decide_approval(
    session: AsyncSession,
    approval: Approval,
    *,
    decision: ApprovalStatus,
    user: User,
    note: str | None = None,
) -> Approval:
    if decision not in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
        raise ApprovalError("decision must be APPROVED or REJECTED")
    if approval.status != ApprovalStatus.PENDING:
        raise ApprovalError(f"Approval {approval.id} was already {approval.status.value}")
    if user.role != UserRole.ADMIN and user.role.value != approval.required_role:
        raise ApprovalError(f"This action requires role '{approval.required_role}', not '{user.role.value}'")

    action = await session.get(ActionRequest, approval.action_request_id)
    if action is None:
        raise ApprovalError("Underlying action request not found")

    approval.status = decision
    approval.decided_by_user_id = user.id
    approval.decided_at = utcnow()
    approval.decision_note = note

    action.status = ActionStatus.APPROVED if decision == ApprovalStatus.APPROVED else ActionStatus.REJECTED
    action.decided_at = utcnow()

    await session.flush()
    await record_audit(
        session,
        case_id=action.case_id,
        entity_type="approval",
        entity_id=approval.id,
        event=f"approval_{decision.value.lower()}",
        actor_type=ActorType.HUMAN_DECISION,
        actor_id=user.id,
        payload={"role": user.role.value, "note": note, "action_request_id": action.id},
    )
    return approval
