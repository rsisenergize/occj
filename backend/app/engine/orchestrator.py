"""Glue: decide the next action, and execute it immediately if it doesn't
need approval. Call repeatedly (API endpoint, or a periodic sweep) to drive
a case forward -- it naturally stalls at whatever needs a human (an
approval, or evidence that hasn't arrived yet)."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.nba_engine import decide_next_action
from app.models.action import ActionRequest
from app.models.case import Case
from app.models.enums import ActionStatus
from app.tools.executor import execute_action


async def advance_case(session: AsyncSession, case: Case) -> ActionRequest | None:
    action = await decide_next_action(session, case)
    if action is None:
        return None
    if action.status in (ActionStatus.PROPOSED, ActionStatus.APPROVED):
        action = await execute_action(session, action)
    return action
