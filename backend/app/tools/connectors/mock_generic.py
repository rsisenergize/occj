"""Mock connectors standing in for POS/OMS/fulfillment/payments/notification/
generic ITSM until real integrations are configured (or always, for the
sources the brief allows to stay simulated: web/app, store, orders,
fulfillment, payments).

Failure behavior is seeded, not random: a caller (demo/seed data, or a test)
opts a specific action into a specific failure mode by setting
`action.target["_simulate"]` to one of "timeout" | "fail_then_succeed" |
"partial_failure". Anything else succeeds immediately. This keeps every
retry/timeout/partial-failure demo reproducible on demand instead of being
luck-of-the-draw in front of reviewers.
"""
import asyncio
import uuid

from app.db import utcnow
from app.models.action import ActionRequest
from app.models.enums import SourceType
from app.tools.base import Connector, ToolResult

# Timeout scenario sleeps longer than the executor's per-attempt timeout so
# asyncio.wait_for in the executor is what actually raises -- exercising the
# real timeout path, not a fake one.
SIMULATED_TIMEOUT_SLEEP_SECONDS = 30.0


class MockConnector(Connector):
    def __init__(self, name: str):
        self.name = name

    async def execute(self, action: ActionRequest, context: dict, attempt_number: int) -> ToolResult:
        simulate = (action.target or {}).get("_simulate")

        if simulate == "timeout":
            await asyncio.sleep(SIMULATED_TIMEOUT_SLEEP_SECONDS)
            # unreachable under the executor's timeout, kept for direct unit tests
            return ToolResult(success=True, response_payload={"note": "should have timed out"})

        if simulate == "fail_then_succeed" and attempt_number == 1:
            return ToolResult(success=False, error_message="Simulated transient upstream 503")

        if simulate == "partial_failure":
            return ToolResult(
                success=True,
                response_payload={"primary_effect": "completed", "reference": uuid.uuid4().hex[:12]},
                needs_manual_review=True,
                error_message="Confirmation notification to the customer failed to send",
            )

        return self._default_result(action)

    def _default_result(self, action: ActionRequest) -> ToolResult:
        ref = uuid.uuid4().hex[:12]
        option_code = (action.target or {}).get("option_code")

        if self.name == "mock:payments":
            return ToolResult(
                success=True,
                response_payload={"transaction_ref": ref, "amount_usd": action.target.get("estimated_cost_usd", 0)},
            )
        if self.name == "mock:fulfillment":
            return ToolResult(
                success=True,
                response_payload={"shipment_ref": ref, "carrier": "MockCarrier Express", "eta_days": 2},
            )
        if self.name == "mock:oms":
            return ToolResult(success=True, response_payload={"adjustment_ref": ref})
        if self.name == "mock:crm":
            return ToolResult(success=True, response_payload={"gesture_ref": ref})
        if self.name == "mock:notification":
            return ToolResult(success=True, response_payload={"message_ref": ref, "channel": "email", "sent": True})
        if self.name == "mock:itsm":
            incident_ref = f"MOCK-INC-{ref[:6].upper()}"
            case = action.target.get("category", "unknown")
            return ToolResult(
                success=True,
                response_payload={"incident_ref": incident_ref, "correlated": False},
                evidence_to_ingest=[
                    {
                        "source_type": SourceType.ITSM_INCIDENT,
                        "provenance_source": "mock:itsm",
                        "external_ref": incident_ref,
                        "occurred_at": utcnow(),
                        "payload": {
                            "status": "investigating",
                            "title": f"Possible systemic issue: {case}",
                            "severity": "medium",
                            "affected_systems": [],
                        },
                    }
                ],
            )
        return ToolResult(success=True, response_payload={"ref": ref, "option_code": option_code})


RECOVERY_CONNECTOR_MAP: dict[str, str] = {
    "reverse_duplicate_charge": "mock:payments",
    "full_refund": "mock:payments",
    "issue_outstanding_refund": "mock:payments",
    "goodwill_credit": "mock:payments",
    "expedited_reshipment": "mock:fulfillment",
    "replacement_order": "mock:fulfillment",
    "reroute_or_reattempt_delivery": "mock:fulfillment",
    "price_adjustment": "mock:oms",
    "manual_reconciliation_credit": "mock:oms",
    "exceptional_remedy": "mock:crm",
    "apology_status_update": "mock:notification",
}
