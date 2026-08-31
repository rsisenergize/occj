"""Executes an ActionRequest against its resolved connector: bounded
retries, a per-attempt timeout, and safe recovery when only part of the
work succeeded -- the "coordinate tools with permission checks, retries,
timeouts, idempotency and safe recovery" capability from the brief.

Idempotency has two layers:
  1. ActionRequest.idempotency_key (set by the NBA engine) stops the same
     *decision* from being proposed twice.
  2. This executor checks for an existing SUCCEEDED ToolExecution before
     doing anything, so calling execute_action twice on the same
     ActionRequest (a retried API call, a re-triggered sweep) never re-runs
     the connector.
"""
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record as record_audit
from app.db import utcnow
from app.engine.stage import advance_stage
from app.models.action import ActionRequest, ToolExecution
from app.models.enums import ActionType, ActionStatus, ActorType, JourneyStage, ToolExecutionStatus
from app.reconciliation.reconciler import ingest_evidence, reconcile_case
from app.tools import registry
from app.tools.base import ToolResult

_STAGE_ON_SUCCESS = {
    ActionType.ESCALATE_ITSM: JourneyStage.ACTIONS_COORDINATED,
    ActionType.EXECUTE_RECOVERY: JourneyStage.ACTIONS_COORDINATED,
    ActionType.NOTIFY_CUSTOMER: JourneyStage.CUSTOMER_UPDATED,
}

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
PER_ATTEMPT_TIMEOUT_SECONDS = 10.0
RETRY_BACKOFF_SECONDS = [0.5, 2.0]  # between attempts 1->2 and 2->3


async def execute_action(session: AsyncSession, action: ActionRequest) -> ActionRequest:
    existing_success = await session.scalar(
        select(ToolExecution).where(
            ToolExecution.action_request_id == action.id, ToolExecution.status == ToolExecutionStatus.SUCCESS
        )
    )
    if existing_success is not None:
        return action  # already executed -- never re-run the connector

    connector, context = await registry.resolve(session, action)

    action.status = ActionStatus.EXECUTING
    await session.flush()
    await record_audit(
        session,
        case_id=action.case_id,
        entity_type="action_request",
        entity_id=action.id,
        event="executing",
        actor_type=ActorType.AUTOMATED_ACTION,
        actor_id=connector.name,
        payload={},
    )

    result: ToolResult | None = None
    last_error: str | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = utcnow()
        tool_exec = ToolExecution(
            action_request_id=action.id,
            connector=connector.name,
            attempt_number=attempt,
            status=ToolExecutionStatus.PENDING,
            request_payload=action.target,
            started_at=started,
        )
        session.add(tool_exec)
        await session.flush()

        try:
            result = await asyncio.wait_for(
                connector.execute(action, context, attempt), timeout=PER_ATTEMPT_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            tool_exec.status = ToolExecutionStatus.TIMEOUT
            tool_exec.error_message = f"Timed out after {PER_ATTEMPT_TIMEOUT_SECONDS}s"
            tool_exec.finished_at = utcnow()
            last_error = tool_exec.error_message
            result = None
        except Exception as exc:  # connector raised instead of returning a failed ToolResult
            tool_exec.status = ToolExecutionStatus.FAILED
            tool_exec.error_message = str(exc)
            tool_exec.finished_at = utcnow()
            last_error = str(exc)
            logger.exception("Connector %s raised on attempt %s", connector.name, attempt)
            result = None
        else:
            tool_exec.finished_at = utcnow()
            tool_exec.response_payload = result.response_payload
            if result.success:
                tool_exec.status = ToolExecutionStatus.SUCCESS
            else:
                tool_exec.status = ToolExecutionStatus.FAILED
                tool_exec.error_message = result.error_message
                last_error = result.error_message

        await session.flush()
        await record_audit(
            session,
            case_id=action.case_id,
            entity_type="tool_execution",
            entity_id=tool_exec.id,
            event=f"attempt_{tool_exec.status.value}",
            actor_type=ActorType.AUTOMATED_ACTION,
            actor_id=connector.name,
            payload={"attempt": attempt, "error": tool_exec.error_message},
        )

        if result is not None and result.success:
            break
        if attempt < MAX_ATTEMPTS:
            await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])

    if result is not None and result.success:
        for evidence_kwargs in result.evidence_to_ingest:
            await ingest_evidence(
                session,
                customer=context["customer"],
                actor_type=ActorType.AUTOMATED_ACTION,
                **evidence_kwargs,
            )
        if result.evidence_to_ingest and context.get("case") is not None:
            await reconcile_case(session, context["case"])

        action.status = ActionStatus.NEEDS_MANUAL_REVIEW if result.needs_manual_review else ActionStatus.SUCCEEDED
        stage = _STAGE_ON_SUCCESS.get(action.action_type)
        if stage is not None and context.get("case") is not None:
            advance_stage(context["case"], stage)
    else:
        action.status = ActionStatus.FAILED

    action.decided_at = utcnow()
    await session.flush()

    await record_audit(
        session,
        case_id=action.case_id,
        entity_type="action_request",
        entity_id=action.id,
        event=f"action_{action.status.value}",
        actor_type=ActorType.AUTOMATED_ACTION,
        actor_id=connector.name,
        payload={"last_error": last_error} if action.status == ActionStatus.FAILED else {},
    )
    return action
