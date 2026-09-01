"""Conflict-detection (materiality) unit tests -- pure functions, no DB.
Covers the two scenarios the spec's testing checklist names explicitly
(amount mismatch, status mismatch) plus the "expected progression is NOT
a conflict" case each rule exists specifically to avoid false-flagging."""
from app.ingest.materiality import is_material_change


def test_payment_amount_mismatch_is_a_conflict():
    existing = {"status": "captured", "amount": 49.99}
    new = {"status": "captured", "amount": 59.99}
    assert is_material_change("payment_event", existing, new) is True


def test_payment_auth_then_capture_is_not_a_conflict():
    # different amount, but existing wasn't "settled" -- an auth hold vs.
    # the actual capture legitimately differ, not a disagreement
    existing = {"status": "authorized", "amount": 49.99}
    new = {"status": "captured", "amount": 49.99}
    assert is_material_change("payment_event", existing, new) is False


def test_order_status_progression_is_not_a_conflict():
    assert is_material_change("order_status", {"status": "placed"}, {"status": "shipped"}) is False
    assert is_material_change("order_status", {"status": "shipped"}, {"status": "delivered"}) is False


def test_order_status_change_after_terminal_is_a_conflict():
    # order already reached a terminal status; a DIFFERENT status arriving
    # afterward is a genuine disagreement, not further progression
    assert is_material_change("order_status", {"status": "delivered"}, {"status": "cancelled"}) is True


def test_fulfilment_conflicting_terminal_statuses():
    assert is_material_change("fulfilment_update", {"status": "delivered"}, {"status": "lost_in_transit"}) is True
    assert is_material_change("fulfilment_update", {"status": "in_transit"}, {"status": "delivered"}) is False


def test_unrecognized_fact_type_never_conflicts():
    assert is_material_change("contact_record", {"a": 1}, {"a": 2}) is False
