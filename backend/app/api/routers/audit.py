from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.replay import get_case_audit_trail, replay_case_state
from app.auth.deps import get_current_user
from app.db import get_session
from app.models.auth import User
from app.models.case import Case
from app.schemas.common import AuditEntryOut

router = APIRouter(prefix="/cases/{case_id}", tags=["audit"])


async def _load_case_or_404(session: AsyncSession, case_id: str) -> Case:
    case = await session.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


@router.get("/audit", response_model=list[AuditEntryOut])
async def audit_trail(
    case_id: str,
    as_of: datetime | None = None,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> list:
    await _load_case_or_404(session, case_id)
    return await get_case_audit_trail(session, case_id, as_of)


@router.get("/replay")
async def replay(
    case_id: str,
    as_of: datetime | None = None,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> dict:
    await _load_case_or_404(session, case_id)
    return await replay_case_state(session, case_id, as_of)
