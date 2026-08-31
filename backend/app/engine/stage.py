"""Case.stage is informational/display -- the 9-stage reference journey
mapped onto whatever the case is actually doing. `advance_stage` only moves
forward; a re-evaluation that jumps the case back to FAILURE_LOCATED sets
case.stage directly instead, which is the one deliberate exception."""
from app.models.case import Case
from app.models.enums import JourneyStage

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


def advance_stage(case: Case, new_stage: JourneyStage) -> None:
    if _INDEX[new_stage] > _INDEX[case.stage]:
        case.stage = new_stage
