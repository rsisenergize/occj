"""Case.stage is informational/display -- the 9-stage reference journey
mapped onto whatever the case is actually doing. `advance_stage` only moves
forward and always writes an audit entry for the transition, which is what
makes audit replay able to answer "what stage was this case at, at time T"
without a separate snapshot table. A re-evaluation that jumps the case back
to FAILURE_LOCATED sets case.stage directly instead (see hypothesis_engine),
which is the one deliberate exception -- that regression is audited as part
of the reevaluation_triggered entry rather than a second stage_advanced one.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record as record_audit
from app.models.case import Case
from app.models.enums import ActorType, JourneyStage

STAGE_ORDER = [
    JourneyStage.ISSUE_REPORTED,
    JourneyStage.JOURNEY_ASSEMBLED,
    JourneyStage.FAILURE_LOCATED,
    JourneyStage.EVIDENCE_CHECKED,
    JourneyStage.IMPACT_ASSESSED,
    JourneyStage.RECOVERY_OPTIONS_RANKED,
    JourneyStage.ACTIONS_COORDINATED,
    JourneyStage.CUSTOMER_UPDATED,
    JourneyStage.OUTCOME_RETAINED,
]
_INDEX = {stage: i for i, stage in enumerate(STAGE_ORDER)}


async def advance_stage(session: AsyncSession, case: Case, new_stage: JourneyStage) -> None:
    if _INDEX[new_stage] <= _INDEX[case.stage]:
        return
    old_stage = case.stage
    case.stage = new_stage
    await record_audit(
        session,
        case_id=case.id,
        entity_type="case",
        entity_id=case.id,
        event="stage_advanced",
        actor_type=ActorType.SYSTEM,
        actor_id="stage_tracker",
        payload={"from": old_stage.value, "to": new_stage.value},
    )
