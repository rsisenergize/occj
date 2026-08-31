"""Real Freshservice integration: ITSM evidence source (correlate a case
with an existing internal incident) and escalation target (raise a new
incident when nothing existing explains the failure). Used for the
ESCALATE_ITSM action type -- see app/engine/nba_engine.py's systemic-cause
check.

NOTE: same caveat as freshdesk.py -- written against the documented
Freshservice API v2 shape, not yet exercised against a live trial account.
Wrapped so a wrong assumption fails as a normal ToolResult, not a crash.
"""
from datetime import datetime, timedelta

import httpx

from app.config import get_settings
from app.db import ensure_aware, utcnow
from app.models.action import ActionRequest
from app.models.enums import SourceType
from app.tools.base import Connector, ConnectorError, ToolResult

settings = get_settings()

# Freshservice ticket "type" field values relevant here; "priority"/"status"
# are the numeric codes from their documented enums (2=Medium, 2=Open).
INCIDENT_TYPE = "Incident"
DEFAULT_PRIORITY = 2
DEFAULT_STATUS_OPEN = 2

# How far back to look for a possibly-correlated incident relative to when
# the failure evidence occurred.
CORRELATION_WINDOW = timedelta(hours=48)


def _client() -> httpx.AsyncClient:
    if not settings.freshservice_configured:
        raise ConnectorError("Freshservice not configured")
    return httpx.AsyncClient(
        base_url=f"https://{settings.freshservice_domain}.freshservice.com/api/v2",
        auth=(settings.freshservice_api_key, "X"),
        timeout=15.0,
    )


def _looks_correlated(ticket: dict, category: str) -> bool:
    keywords = category.replace("_", " ").split()
    haystack = f"{ticket.get('subject', '')} {ticket.get('description_text', '')}".lower()
    return any(kw in haystack for kw in keywords if len(kw) > 3)


class FreshserviceConnector(Connector):
    name = "freshservice"

    async def execute(self, action: ActionRequest, context: dict, attempt_number: int) -> ToolResult:
        category = (action.target or {}).get("category", "unknown")
        case = context.get("case")

        try:
            async with _client() as client:
                since = (utcnow() - CORRELATION_WINDOW).isoformat()
                resp = await client.get("/tickets", params={"updated_since": since, "type": INCIDENT_TYPE})
                resp.raise_for_status()
                tickets = resp.json().get("tickets", [])

                correlated = next((t for t in tickets if _looks_correlated(t, category)), None)
                if correlated:
                    return ToolResult(
                        success=True,
                        response_payload={"correlated_incident_id": correlated["id"], "subject": correlated.get("subject")},
                        evidence_to_ingest=[
                            {
                                "source_type": SourceType.ITSM_INCIDENT,
                                "provenance_source": "freshservice",
                                "external_ref": str(correlated["id"]),
                                "occurred_at": datetime.fromisoformat(
                                    correlated["created_at"].replace("Z", "+00:00")
                                ),
                                "order_id": case.order_id if case else None,
                                "payload": {
                                    "status": correlated.get("status_name", "open"),
                                    "title": correlated.get("subject", ""),
                                    "severity": correlated.get("priority_name", "medium"),
                                    "affected_systems": [],
                                },
                            }
                        ],
                    )

                create_resp = await client.post(
                    "/tickets",
                    json={
                        "subject": f"Possible systemic issue: {category}",
                        "description": action.rationale,
                        "email": "ops-automation@occj.internal",
                        "priority": DEFAULT_PRIORITY,
                        "status": DEFAULT_STATUS_OPEN,
                        "source": 2,
                        "type": INCIDENT_TYPE,
                    },
                )
                create_resp.raise_for_status()
                new_ticket = create_resp.json().get("ticket", {})
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error_message=f"Freshservice call failed: {exc}")

        return ToolResult(
            success=True,
            response_payload={"created_incident_id": new_ticket.get("id")},
            evidence_to_ingest=[
                {
                    "source_type": SourceType.ITSM_INCIDENT,
                    "provenance_source": "freshservice",
                    "external_ref": str(new_ticket.get("id")),
                    "occurred_at": utcnow(),
                    "order_id": case.order_id if case else None,
                    "payload": {
                        "status": "investigating",
                        "title": f"Possible systemic issue: {category}",
                        "severity": "medium",
                        "affected_systems": [],
                    },
                }
            ],
        )
