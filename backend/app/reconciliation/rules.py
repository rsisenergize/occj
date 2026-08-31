"""Payload conventions and reconciliation rules.

Every EvidenceRecord.payload is a plain JSON dict; the fields below are the
convention every ingestion adapter (mock or real: Freshdesk, Freshservice)
is expected to populate. Reconciliation reads these defensively (.get) so a
source that omits an optional field degrades to "unknown" rather than
crashing -- consistent with the requirement to make uncertainty explicit
instead of assuming.

    WEB_APP_EVENT:          {event, session_id, url, device}
    STORE_TRANSACTION:      {register_id, store_id, items, amount, transaction_type}
    ORDER:                  {status, amount, items, shipping_address, channel}
    FULFILLMENT_UPDATE:     {status, carrier, tracking_number, eta}
    PAYMENT:                {status, amount, method, gateway_ref}
    CONTACT_CENTER_RECORD:  {channel, subject, body, disposition, ticket_id}
    RETURN:                 {status, amount, reason}
    ITSM_INCIDENT:          {status, title, affected_systems, severity}
"""
from datetime import timedelta

from app.models.enums import SourceType

# For a given source_type, the source_type expected to follow it and the SLA
# window within which that follow-up should normally arrive. Used to raise
# "missing evidence" flags -- an expected follow-up that hasn't shown up in
# time is itself evidence of a possible failure point, not just an ingestion
# gap.
EXPECTED_FOLLOWUPS: dict[SourceType, tuple[SourceType, timedelta]] = {
    SourceType.ORDER: (SourceType.PAYMENT, timedelta(hours=1)),
    SourceType.PAYMENT: (SourceType.FULFILLMENT_UPDATE, timedelta(hours=48)),
    SourceType.RETURN: (SourceType.PAYMENT, timedelta(hours=72)),  # refund should follow a received return
}

# Terminal fulfillment statuses that are mutually exclusive for one order --
# seeing more than one of these among current (non-superseded) evidence is a
# contradiction, not a timeline (e.g. "delivered" and "lost_in_transit" can't
# both be true).
FULFILLMENT_TERMINAL_STATUSES = {"delivered", "lost_in_transit", "returned_to_sender", "delivery_failed"}

# Contact-centre dispositions that indicate the customer is disputing a fact
# another source system has already recorded as resolved/complete.
DISPUTE_DISPOSITIONS = {"item_not_received", "wrong_item", "disputes_delivery", "unauthorized_charge"}
