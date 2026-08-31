from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.service import ApprovalError, decide_approval
from app.auth.deps import get_current_user
from app.db import get_session
from app.engine.orchestrator import advance_case
from app.models.action import ActionRequest, Approval
from app.models.auth import User
from app.models.case import Case
from app.models.enums import ActionStatus, ApprovalStatus, UserRole
from app.schemas.common import ApprovalDecision, ApprovalOut

_STALLING_STATUSES = {ActionStatus.PENDING_APPROVAL, ActionStatus.NEEDS_MANUAL_REVIEW, ActionStatus.FAILED}

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _with_case_id(approval: Approval, case_id: str | None) -> ApprovalOut:
    return ApprovalOut.model_validate(approval).model_copy(update={"case_id": case_id})


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)
) -> list[ApprovalOut]:
    """Pending approvals routed to the current user's role (admins see all)."""
    query = (
        select(Approval, ActionRequest.case_id)
        .join(ActionRequest, Approval.action_request_id == ActionRequest.id)
        .where(Approval.status == ApprovalStatus.PENDING)
        .order_by(Approval.created_at)
    )
    if user.role != UserRole.ADMIN:
        query = query.where(Approval.required_role == user.role.value)
    rows = (await session.execute(query)).all()
    return [_with_case_id(approval, case_id) for approval, case_id in rows]


@router.post("/{approval_id}/decide", response_model=ApprovalOut)
async def decide(
    approval_id: str,
    body: ApprovalDecision,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ApprovalOut:
    approval = await session.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval not found")

    decision = ApprovalStatus.APPROVED if body.decision.lower() == "approved" else ApprovalStatus.REJECTED
    try:
        approval = await decide_approval(session, approval, decision=decision, user=user, note=body.note)
    except ApprovalError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    await session.commit()

    action = await session.get(ActionRequest, approval.action_request_id)
    case_id = action.case_id if action else None

    if decision == ApprovalStatus.APPROVED and action is not None:
        case = await session.get(Case, action.case_id)
        # Execute the now-approved action, then keep driving the pipeline
        # (notify customer, close case, ...) until it stalls on its own.
        for _ in range(12):
            next_action = await advance_case(session, case)
            if next_action is None or next_action.status in _STALLING_STATUSES:
                break
        await session.commit()

    await session.refresh(approval)
    return _with_case_id(approval, case_id)
