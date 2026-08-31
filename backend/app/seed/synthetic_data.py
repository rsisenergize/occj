"""Synthetic starter data: representative journeys across every source
system plus the edge cases the brief calls out explicitly -- corrections,
duplicates, contradictions, all three case-creation triggers, and a mix of
case states (some fully closed, some deliberately left mid-pipeline so the
seeded workspace has live approval-queue and pending-evidence work to look
at, not just a pile of finished cases).
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.engine.case_service import create_case, get_or_create_customer, run_case_cycle
from app.engine.orchestrator import advance_case
from app.models.action import ActionRequest, Approval
from app.models.enums import ActionStatus, ApprovalStatus, CaseTriggerType, SourceType
from app.reconciliation.reconciler import ingest_evidence

NOW = datetime.now(UTC)


def _ago(**kwargs) -> datetime:
    return NOW - timedelta(**kwargs)


async def _auto_approve_to_closure(session: AsyncSession, case, max_rounds: int = 12) -> None:
    """Demo-only helper: approve whatever's pending as a stand-in supervisor/
    finance action, so a couple of seeded cases show the *complete* journey
    end-to-end rather than every case stopping at the first approval gate."""
    for _ in range(max_rounds):
        pending = await session.scalar(
            select(Approval)
            .join(ActionRequest, Approval.action_request_id == ActionRequest.id)
            .where(Approval.status == ApprovalStatus.PENDING, ActionRequest.case_id == case.id)
            .order_by(Approval.created_at)
        )
        if pending is None:
            action = await advance_case(session, case)
            if action is None:
                break
            continue
        pending.status = ApprovalStatus.APPROVED
        pending.decided_at = NOW
        pending.decision_note = "Auto-approved by seed script for demo purposes"
        action = await session.get(ActionRequest, pending.action_request_id)
        action.status = ActionStatus.APPROVED
        await session.flush()
        await advance_case(session, case)


async def seed_all(session: AsyncSession) -> dict:
    created_case_ids: list[str] = []

    # --- 1. Duplicate charge (gold tier) -- left pending finance approval ---
    cust1 = await get_or_create_customer(
        session, external_customer_id="cust-1001", display_name="Priya Nair", tier="gold", email="priya@example.com"
    )
    case1 = await create_case(session, customer=cust1, trigger_type=CaseTriggerType.CUSTOMER_CONTACT, order_id="ord-1001")
    await ingest_evidence(session, customer=cust1, source_type=SourceType.ORDER, provenance_source="mock:oms",
                           external_ref="ord-1001", occurred_at=_ago(hours=30), order_id="ord-1001",
                           payload={"status": "confirmed", "amount": 189.99, "channel": "online"})
    await ingest_evidence(session, customer=cust1, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
                           external_ref="pay-1001a", occurred_at=_ago(hours=30, minutes=-2), order_id="ord-1001",
                           payload={"status": "captured", "amount": 189.99, "method": "card"})
    await ingest_evidence(session, customer=cust1, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
                           external_ref="pay-1001b", occurred_at=_ago(hours=30, minutes=-3), order_id="ord-1001",
                           payload={"status": "captured", "amount": 189.99, "method": "card"})
    await ingest_evidence(session, customer=cust1, source_type=SourceType.CONTACT_CENTER_RECORD, provenance_source="freshdesk",
                           external_ref="fd-9001", occurred_at=_ago(hours=20), order_id="ord-1001",
                           payload={"channel": "ticket", "ticket_id": 9001, "subject": "Charged twice for my order",
                                     "body": "I see two charges of $189.99 on my card for the same order.",
                                     "disposition": "unauthorized_charge", "status": "open"})
    await run_case_cycle(session, case1)
    await _auto_approve_to_closure(session, case1)  # demonstrates the full approve -> execute -> notify -> close loop
    await session.flush()
    created_case_ids.append(case1.id)

    # --- 2. Fulfillment never started (standard tier) -- run to full closure ---
    cust2 = await get_or_create_customer(session, external_customer_id="cust-1002", display_name="Marcus Webb", tier="standard")
    case2 = await create_case(session, customer=cust2, trigger_type=CaseTriggerType.SYSTEM_DETECTED, order_id="ord-1002")
    await ingest_evidence(session, customer=cust2, source_type=SourceType.ORDER, provenance_source="mock:oms",
                           external_ref="ord-1002", occurred_at=_ago(days=4), order_id="ord-1002",
                           payload={"status": "confirmed", "amount": 64.50, "channel": "online"})
    await ingest_evidence(session, customer=cust2, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
                           external_ref="pay-1002", occurred_at=_ago(days=4, minutes=-5), order_id="ord-1002",
                           payload={"status": "captured", "amount": 64.50, "method": "card"})
    await run_case_cycle(session, case2)
    await _auto_approve_to_closure(session, case2)
    await session.flush()
    created_case_ids.append(case2.id)

    # --- 3. Fulfillment never started #2 (silver tier) -- left pending approval ---
    cust3 = await get_or_create_customer(session, external_customer_id="cust-1003", display_name="Elena Kova", tier="silver")
    case3 = await create_case(session, customer=cust3, trigger_type=CaseTriggerType.CUSTOMER_CONTACT, order_id="ord-1003")
    await ingest_evidence(session, customer=cust3, source_type=SourceType.ORDER, provenance_source="mock:oms",
                           external_ref="ord-1003", occurred_at=_ago(days=3), order_id="ord-1003",
                           payload={"status": "confirmed", "amount": 142.00, "channel": "app"})
    await ingest_evidence(session, customer=cust3, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
                           external_ref="pay-1003", occurred_at=_ago(days=3, minutes=-5), order_id="ord-1003",
                           payload={"status": "captured", "amount": 142.00, "method": "wallet"})
    await ingest_evidence(session, customer=cust3, source_type=SourceType.CONTACT_CENTER_RECORD, provenance_source="freshdesk",
                           external_ref="fd-9003", occurred_at=_ago(hours=6), order_id="ord-1003",
                           payload={"channel": "chat", "ticket_id": 9003, "subject": "Order never shipped",
                                     "body": "It has been 3 days and tracking hasn't updated at all.",
                                     "disposition": "open", "status": "open"})
    await run_case_cycle(session, case3)
    await session.flush()
    created_case_ids.append(case3.id)

    # --- 4. Delivered but disputed (platinum tier) -- left pending approval ---
    cust4 = await get_or_create_customer(session, external_customer_id="cust-1004", display_name="Diego Fuentes", tier="platinum")
    case4 = await create_case(session, customer=cust4, trigger_type=CaseTriggerType.CUSTOMER_CONTACT, order_id="ord-1004")
    await ingest_evidence(session, customer=cust4, source_type=SourceType.ORDER, provenance_source="mock:oms",
                           external_ref="ord-1004", occurred_at=_ago(days=2), order_id="ord-1004",
                           payload={"status": "confirmed", "amount": 310.00, "channel": "online"})
    await ingest_evidence(session, customer=cust4, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
                           external_ref="pay-1004", occurred_at=_ago(days=2, minutes=-5), order_id="ord-1004",
                           payload={"status": "captured", "amount": 310.00, "method": "card"})
    await ingest_evidence(session, customer=cust4, source_type=SourceType.FULFILLMENT_UPDATE, provenance_source="mock:fulfillment",
                           external_ref="ship-1004", occurred_at=_ago(days=1), order_id="ord-1004",
                           payload={"status": "delivered", "carrier": "MockCarrier Express", "tracking_number": "MCE123"})
    await ingest_evidence(session, customer=cust4, source_type=SourceType.CONTACT_CENTER_RECORD, provenance_source="freshdesk",
                           external_ref="fd-9004", occurred_at=_ago(hours=10), order_id="ord-1004",
                           payload={"channel": "call", "ticket_id": 9004, "subject": "Package marked delivered but not received",
                                     "body": "Tracking says delivered yesterday but nothing is here and no one saw a delivery.",
                                     "disposition": "item_not_received", "status": "open"})
    await run_case_cycle(session, case4)
    await session.flush()
    created_case_ids.append(case4.id)

    # --- 5. Return received, refund not issued (standard tier) -- run to closure ---
    cust5 = await get_or_create_customer(session, external_customer_id="cust-1005", display_name="Aisha Bello", tier="standard")
    case5 = await create_case(session, customer=cust5, trigger_type=CaseTriggerType.CUSTOMER_CONTACT, order_id="ord-1005")
    await ingest_evidence(session, customer=cust5, source_type=SourceType.ORDER, provenance_source="mock:oms",
                           external_ref="ord-1005", occurred_at=_ago(days=10), order_id="ord-1005",
                           payload={"status": "confirmed", "amount": 88.00, "channel": "in_store"})
    await ingest_evidence(session, customer=cust5, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
                           external_ref="pay-1005", occurred_at=_ago(days=10, minutes=-5), order_id="ord-1005",
                           payload={"status": "captured", "amount": 88.00, "method": "card"})
    await ingest_evidence(session, customer=cust5, source_type=SourceType.RETURN, provenance_source="mock:returns",
                           external_ref="ret-1005", occurred_at=_ago(days=5), order_id="ord-1005",
                           payload={"status": "received", "amount": 88.00, "reason": "wrong_size"})
    await run_case_cycle(session, case5)
    await _auto_approve_to_closure(session, case5)
    await session.flush()
    created_case_ids.append(case5.id)

    # --- 6. Conflicting fulfillment outcomes (silver tier) ---
    cust6 = await get_or_create_customer(session, external_customer_id="cust-1006", display_name="Tomas Lindqvist", tier="silver")
    case6 = await create_case(session, customer=cust6, trigger_type=CaseTriggerType.SYSTEM_DETECTED, order_id="ord-1006")
    await ingest_evidence(session, customer=cust6, source_type=SourceType.ORDER, provenance_source="mock:oms",
                           external_ref="ord-1006", occurred_at=_ago(days=3), order_id="ord-1006",
                           payload={"status": "confirmed", "amount": 76.20, "channel": "online"})
    await ingest_evidence(session, customer=cust6, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
                           external_ref="pay-1006", occurred_at=_ago(days=3, minutes=-5), order_id="ord-1006",
                           payload={"status": "captured", "amount": 76.20, "method": "card"})
    await ingest_evidence(session, customer=cust6, source_type=SourceType.FULFILLMENT_UPDATE, provenance_source="mock:fulfillment",
                           external_ref="ship-1006a", occurred_at=_ago(days=2), order_id="ord-1006",
                           payload={"status": "out_for_delivery", "carrier": "MockCarrier Express", "tracking_number": "MCE456"})
    await ingest_evidence(session, customer=cust6, source_type=SourceType.FULFILLMENT_UPDATE, provenance_source="mock:fulfillment",
                           external_ref="ship-1006b", occurred_at=_ago(days=1, hours=12), order_id="ord-1006",
                           payload={"status": "lost_in_transit", "carrier": "MockCarrier Express", "tracking_number": "MCE456"})
    await ingest_evidence(session, customer=cust6, source_type=SourceType.FULFILLMENT_UPDATE, provenance_source="mock:fulfillment",
                           external_ref="ship-1006c", occurred_at=_ago(hours=6), order_id="ord-1006",
                           payload={"status": "delivered", "carrier": "MockCarrier Express", "tracking_number": "MCE456"})
    await run_case_cycle(session, case6)
    await session.flush()
    created_case_ids.append(case6.id)

    # --- 7. Provenance/correction demo (standard tier) -- address corrected after the fact ---
    cust7 = await get_or_create_customer(session, external_customer_id="cust-1007", display_name="Noah Kim", tier="standard")
    case7 = await create_case(session, customer=cust7, trigger_type=CaseTriggerType.MANUAL, order_id="ord-1007",
                               summary="Customer called to correct their shipping address before dispatch")
    await ingest_evidence(session, customer=cust7, source_type=SourceType.ORDER, provenance_source="mock:oms",
                           external_ref="ord-1007", occurred_at=_ago(hours=5), order_id="ord-1007",
                           payload={"status": "confirmed", "amount": 54.00, "channel": "online",
                                     "shipping_address": "12 Old St, Springfield"})
    # correction: same external_ref, different payload -> supersedes chain
    await ingest_evidence(session, customer=cust7, source_type=SourceType.ORDER, provenance_source="mock:oms",
                           external_ref="ord-1007", occurred_at=_ago(hours=4), order_id="ord-1007",
                           payload={"status": "confirmed", "amount": 54.00, "channel": "online",
                                     "shipping_address": "88 New Ave, Springfield"})
    await run_case_cycle(session, case7)
    await session.flush()
    created_case_ids.append(case7.id)

    # --- 8. Duplicate charge, system-detected (no customer contact yet) ---
    cust8 = await get_or_create_customer(session, external_customer_id="cust-1008", display_name="Rina Chatterjee", tier="gold")
    case8 = await create_case(session, customer=cust8, trigger_type=CaseTriggerType.SYSTEM_DETECTED, order_id="ord-1008")
    await ingest_evidence(session, customer=cust8, source_type=SourceType.ORDER, provenance_source="mock:oms",
                           external_ref="ord-1008", occurred_at=_ago(hours=8), order_id="ord-1008",
                           payload={"status": "confirmed", "amount": 220.00, "channel": "online"})
    await ingest_evidence(session, customer=cust8, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
                           external_ref="pay-1008a", occurred_at=_ago(hours=8, minutes=-1), order_id="ord-1008",
                           payload={"status": "captured", "amount": 220.00, "method": "card"})
    await ingest_evidence(session, customer=cust8, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
                           external_ref="pay-1008b", occurred_at=_ago(hours=7, minutes=59), order_id="ord-1008",
                           payload={"status": "captured", "amount": 220.00, "method": "card"})
    await run_case_cycle(session, case8)
    await session.flush()
    created_case_ids.append(case8.id)

    await session.commit()
    return {"cases_created": created_case_ids, "count": len(created_case_ids)}


async def main() -> None:
    async with AsyncSessionLocal() as session:
        result = await seed_all(session)
        print(f"Seeded {result['count']} demo cases: {result['cases_created']}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
