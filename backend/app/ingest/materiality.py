"""Per-fact_type materiality rules: is a new version of a fact meaningfully
*different* from the prior one, or is it an expected progression that
shouldn't be flagged?

This is deliberately narrow and explicit, not a generic "payload changed"
diff -- a generic diff would flag every normal order-status progression
(placed -> shipped -> delivered) as a "conflict," which is wrong. This
mirrors app/reconciliation/rules.py's approach in the existing pipeline
(a small set of targeted, reasoned rules rather than exhaustive coverage):
only order_status, payment_event, and fulfilment_update get a rule here;
everything else is treated as append-only history with no automatic
conflict detection, which is an intentional scope decision -- see README.
"""
from typing import Any

ORDER_TERMINAL_STATUSES = {"delivered", "cancelled", "refunded"}
FULFILMENT_TERMINAL_STATUSES = {"delivered", "lost_in_transit", "returned_to_sender"}
SETTLED_PAYMENT_STATUSES = {"captured", "settled"}


def is_material_change(fact_type: str, existing_payload: dict[str, Any], new_payload: dict[str, Any]) -> bool:
    """True if (existing, new) represents a genuine disagreement worth
    surfacing as a conflict, for the fact types this module has an
    explicit rule for. Returns False (no conflict) for anything else,
    including a fact_type with no rule at all."""
    if fact_type == "order_status":
        return _order_status_conflict(existing_payload, new_payload)
    if fact_type == "payment_event":
        return _payment_amount_conflict(existing_payload, new_payload)
    if fact_type == "fulfilment_update":
        return _fulfilment_conflict(existing_payload, new_payload)
    return False


def _order_status_conflict(existing: dict[str, Any], new: dict[str, Any]) -> bool:
    existing_status = existing.get("status")
    new_status = new.get("status")
    if existing_status == new_status:
        return False
    # Progressing through non-terminal statuses (placed -> confirmed ->
    # shipped) is expected, not a conflict. Only a *different* status
    # arriving after the order already reached a terminal one is a real
    # disagreement (e.g. "delivered" then later "cancelled" from another
    # source, or vice versa).
    return existing_status in ORDER_TERMINAL_STATUSES


def _payment_amount_conflict(existing: dict[str, Any], new: dict[str, Any]) -> bool:
    if existing.get("status") not in SETTLED_PAYMENT_STATUSES or new.get("status") not in SETTLED_PAYMENT_STATUSES:
        return False  # e.g. an auth vs. a capture legitimately differ
    return existing.get("amount") != new.get("amount")


def _fulfilment_conflict(existing: dict[str, Any], new: dict[str, Any]) -> bool:
    existing_status = existing.get("status")
    new_status = new.get("status")
    if existing_status == new_status:
        return False
    return existing_status in FULFILMENT_TERMINAL_STATUSES and new_status in FULFILMENT_TERMINAL_STATUSES
