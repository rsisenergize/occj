"""Resolves which connector (real or mock) handles a given ActionRequest,
and assembles the read-only context that connector needs.

This is the one place that decides "real integration vs. mock fallback" --
callers of the executor never branch on whether Freshdesk/Freshservice
credentials exist.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.action import ActionRequest
from app.models.case import Case, Customer
from app.models.enums import ActionType, SourceType
from app.models.evidence import EvidenceRecord
from app.tools.base import Connector
from app.tools.connectors.freshdesk import FreshdeskConnector
from app.tools.connectors.freshservice import FreshserviceConnector
from app.tools.connectors.mock_generic import RECOVERY_CONNECTOR_MAP, MockConnector

settings = get_settings()


async def resolve(session: AsyncSession, action: ActionRequest) -> tuple[Connector, dict]:
    case = await session.get(Case, action.case_id)
    customer = await session.get(Customer, case.customer_id) if case else None
    context: dict = {"case": case, "customer": customer}

    if action.action_type == ActionType.ESCALATE_ITSM:
        if settings.freshservice_configured:
            return FreshserviceConnector(), context
        return MockConnector("mock:itsm"), context

    if action.action_type == ActionType.NOTIFY_CUSTOMER:
        if settings.freshdesk_configured and case is not None:
            ticket_evidence = await session.scalar(
                select(EvidenceRecord)
                .where(
                    EvidenceRecord.customer_id == case.customer_id,
                    EvidenceRecord.source_type == SourceType.CONTACT_CENTER_RECORD,
                    EvidenceRecord.provenance_source == "freshdesk",
                    EvidenceRecord.is_superseded.is_(False),
                )
                .order_by(EvidenceRecord.occurred_at.desc())
            )
            if ticket_evidence is not None:
                context["ticket_id"] = (ticket_evidence.payload or {}).get("ticket_id") or ticket_evidence.external_ref
                return FreshdeskConnector(), context
        return MockConnector("mock:notification"), context

    if action.action_type == ActionType.EXECUTE_RECOVERY:
        option_code = (action.target or {}).get("option_code")
        connector_name = RECOVERY_CONNECTOR_MAP.get(option_code, "mock:generic")
        return MockConnector(connector_name), context

    return MockConnector(f"mock:{action.action_type.value}"), context
