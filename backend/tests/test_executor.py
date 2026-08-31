from sqlalchemy import select

import app.tools.connectors.mock_generic as mock_generic
import app.tools.executor as executor_mod
from app.models.action import ActionRequest, ToolExecution
from app.models.enums import ActionStatus, ActionType, CaseTriggerType, ToolExecutionStatus
from tests.conftest import make_case, make_customer


async def _make_action(session, case, simulate: str | None, code: str = "full_refund") -> ActionRequest:
    action = ActionRequest(
        case_id=case.id,
        action_type=ActionType.EXECUTE_RECOVERY,
        target={"option_code": code, "estimated_cost_usd": 10.0, "_simulate": simulate},
        rationale="test",
        expected_value=1.0,
        status=ActionStatus.PROPOSED,
        requires_approval=False,
        idempotency_key=f"test-{simulate}-{code}",
    )
    session.add(action)
    await session.flush()
    return action


async def test_seeded_transient_failure_then_succeeds(session, now, monkeypatch):
    monkeypatch.setattr(executor_mod, "RETRY_BACKOFF_SECONDS", [0, 0])
    customer = await make_customer(session)
    case = await make_case(session, customer, trigger_type=CaseTriggerType.MANUAL)
    action = await _make_action(session, case, "fail_then_succeed")

    result = await executor_mod.execute_action(session, action)

    assert result.status == ActionStatus.SUCCEEDED
    execs = list(await session.scalars(select(ToolExecution).where(ToolExecution.action_request_id == action.id)))
    assert [e.status for e in execs] == [ToolExecutionStatus.FAILED, ToolExecutionStatus.SUCCESS]


async def test_seeded_partial_failure_needs_manual_review(session, now):
    customer = await make_customer(session)
    case = await make_case(session, customer, trigger_type=CaseTriggerType.MANUAL)
    action = await _make_action(session, case, "partial_failure")

    result = await executor_mod.execute_action(session, action)
    assert result.status == ActionStatus.NEEDS_MANUAL_REVIEW


async def test_seeded_timeout_exhausts_retries_and_fails(session, now, monkeypatch):
    monkeypatch.setattr(executor_mod, "PER_ATTEMPT_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(executor_mod, "RETRY_BACKOFF_SECONDS", [0, 0])
    monkeypatch.setattr(mock_generic, "SIMULATED_TIMEOUT_SLEEP_SECONDS", 1.0)
    customer = await make_customer(session)
    case = await make_case(session, customer, trigger_type=CaseTriggerType.MANUAL)
    action = await _make_action(session, case, "timeout")

    result = await executor_mod.execute_action(session, action)
    assert result.status == ActionStatus.FAILED
    execs = list(await session.scalars(select(ToolExecution).where(ToolExecution.action_request_id == action.id)))
    assert len(execs) == executor_mod.MAX_ATTEMPTS
    assert all(e.status == ToolExecutionStatus.TIMEOUT for e in execs)


async def test_execution_is_idempotent_once_succeeded(session, now):
    customer = await make_customer(session)
    case = await make_case(session, customer, trigger_type=CaseTriggerType.MANUAL)
    action = await _make_action(session, case, None)

    await executor_mod.execute_action(session, action)
    execs_before = list(await session.scalars(select(ToolExecution).where(ToolExecution.action_request_id == action.id)))

    await executor_mod.execute_action(session, action)  # calling again must not re-run the connector
    execs_after = list(await session.scalars(select(ToolExecution).where(ToolExecution.action_request_id == action.id)))

    assert len(execs_before) == len(execs_after) == 1
