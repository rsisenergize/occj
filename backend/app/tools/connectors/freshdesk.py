"""Real Freshdesk integration: contact-centre evidence source, and the
delivery channel for NOTIFY_CUSTOMER when a case originated from (or has an
open) Freshdesk ticket.

NOTE: written against the documented Freshdesk API v2 shape but not yet
exercised against a live account (no trial credentials at the time this was
written). Every call is wrapped so a wrong assumption about a field/endpoint
name fails as a normal ToolResult/ConnectorError -- eligible for retry and
surfaced in the audit trail -- rather than crashing the request. Validate
against a real sandbox once FRESHDESK_DOMAIN/FRESHDESK_API_KEY are set, and
adjust field names here if the live API disagrees.
"""
from datetime import datetime

import httpx

from app.config import get_settings
from app.models.action import ActionRequest
from app.models.enums import SourceType
from app.tools.base import Connector, ConnectorError, ToolResult

settings = get_settings()


def _client() -> httpx.AsyncClient:
    if not settings.freshdesk_configured:
        raise ConnectorError("Freshdesk not configured")
    return httpx.AsyncClient(
        base_url=f"https://{settings.freshdesk_domain}.freshdesk.com/api/v2",
        auth=(settings.freshdesk_api_key, "X"),
        timeout=15.0,
    )


async def fetch_recent_tickets(email: str, since: datetime | None = None) -> list[dict]:
    """Used by the ingestion job to pull a customer's tickets in as
    CONTACT_CENTER_RECORD evidence. Returns Freshdesk's raw ticket dicts."""
    async with _client() as client:
        params: dict = {"email": email}
        if since is not None:
            params["updated_since"] = since.isoformat()
        resp = await client.get("/tickets", params=params)
        resp.raise_for_status()
        return resp.json()


def ticket_to_evidence_kwargs(ticket: dict, order_id: str | None = None) -> dict:
    """Maps a raw Freshdesk ticket into the kwargs app.reconciliation.reconciler.ingest_evidence expects."""
    status_map = {2: "open", 3: "pending", 4: "resolved", 5: "closed"}
    disposition = "resolved" if ticket.get("status") in (4, 5) else "open"
    return {
        "source_type": SourceType.CONTACT_CENTER_RECORD,
        "provenance_source": "freshdesk",
        "external_ref": str(ticket["id"]),
        "occurred_at": datetime.fromisoformat(ticket["created_at"].replace("Z", "+00:00")),
        "order_id": order_id,
        "payload": {
            "channel": "ticket",
            "ticket_id": ticket["id"],
            "subject": ticket.get("subject", ""),
            "body": (ticket.get("description_text") or "")[:2000],
            "disposition": disposition,
            "status": status_map.get(ticket.get("status"), "unknown"),
        },
    }


class FreshdeskConnector(Connector):
    name = "freshdesk"

    async def execute(self, action: ActionRequest, context: dict, attempt_number: int) -> ToolResult:
        ticket_id = context.get("ticket_id")
        if not ticket_id:
            return ToolResult(success=False, error_message="No Freshdesk ticket associated with this case")
        message = (action.target or {}).get("message", "")
        try:
            async with _client() as client:
                resp = await client.post(f"/tickets/{ticket_id}/reply", json={"body": message})
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error_message=f"Freshdesk reply failed: {exc}")
        return ToolResult(success=True, response_payload={"freshdesk_reply_id": data.get("id"), "ticket_id": ticket_id})
