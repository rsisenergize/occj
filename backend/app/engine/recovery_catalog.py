"""Tiered recovery/compensation catalog. Deterministic and rule-based on
purpose: which remedies apply to which hypothesis category, their estimated
cost, and whether that cost clears the approval threshold -- all of this
needs to be explainable to a reviewer, so none of it is LLM-generated."""
from dataclasses import dataclass, field

from app.config import get_settings

settings = get_settings()


@dataclass
class RecoveryOption:
    code: str
    label: str
    estimated_cost_usd: float
    requires_approval: bool
    approval_role: str | None
    rationale: str
    is_exceptional: bool = False


# category -> option builders. Each builder receives (financial_exposure_usd,
# tier) and returns a RecoveryOption. "exposure" is the largest dollar figure
# implicated by the hypothesis's cited evidence (see impact_engine).
_CATEGORY_OPTIONS: dict[str, list] = {
    "duplicate_charge": [
        lambda exposure, tier: RecoveryOption(
            "reverse_duplicate_charge",
            f"Reverse duplicate charge (${exposure:.2f})",
            exposure,
            exposure >= settings.high_value_approval_threshold_usd,
            "finance_approver",
            "A second capture was recorded for the same order; reversing it restores the correct charge.",
        )
    ],
    "order_confirmed_fulfillment_never_started": [
        lambda exposure, tier: RecoveryOption(
            "expedited_reshipment",
            "Expedited reshipment at no charge",
            round(exposure * 0.3, 2),
            round(exposure * 0.3, 2) >= settings.high_value_approval_threshold_usd,
            "supervisor",
            "Order was paid but fulfillment never began; reshipping resolves it without a full refund.",
        ),
        lambda exposure, tier: RecoveryOption(
            "full_refund",
            f"Full refund (${exposure:.2f})",
            exposure,
            exposure >= settings.high_value_approval_threshold_usd,
            "finance_approver",
            "Alternative to reshipment when the customer prefers not to wait for a replacement.",
        ),
    ],
    "fulfillment_shows_delivered_customer_disputes_receipt": [
        lambda exposure, tier: RecoveryOption(
            "replacement_order",
            "Replacement order at no additional charge",
            exposure,
            exposure >= settings.high_value_approval_threshold_usd,
            "supervisor",
            "Carrier marked delivered but the customer disputes receipt; replacing the order is the standard remedy pending carrier investigation.",
        ),
        lambda exposure, tier: RecoveryOption(
            "goodwill_credit",
            "Goodwill credit",
            round(min(25.0, exposure * 0.1), 2),
            round(min(25.0, exposure * 0.1), 2) >= settings.high_value_approval_threshold_usd,
            "supervisor",
            "Smaller-footprint remedy while the delivery dispute is investigated further.",
        ),
    ],
    "return_received_refund_not_issued": [
        lambda exposure, tier: RecoveryOption(
            "issue_outstanding_refund",
            f"Issue outstanding refund (${exposure:.2f})",
            exposure,
            exposure >= settings.high_value_approval_threshold_usd,
            "finance_approver",
            "The return was received but no refund was ever issued against it.",
        )
    ],
    "promised_promotion_or_price_not_honored": [
        lambda exposure, tier: RecoveryOption(
            "price_adjustment",
            "Retroactive price adjustment / credit",
            exposure,
            exposure >= settings.high_value_approval_threshold_usd,
            "supervisor",
            "The promised price/promotion was not honored at checkout or fulfillment.",
        )
    ],
    "wrong_address_or_failed_delivery_attempt": [
        lambda exposure, tier: RecoveryOption(
            "reroute_or_reattempt_delivery",
            "Reroute / re-attempt delivery",
            round(exposure * 0.15, 2),
            False,
            None,
            "Address or delivery-attempt issue; lowest-cost remedy is usually a corrected delivery attempt.",
        ),
        lambda exposure, tier: RecoveryOption(
            "full_refund",
            f"Full refund (${exposure:.2f})",
            exposure,
            exposure >= settings.high_value_approval_threshold_usd,
            "finance_approver",
            "Fallback when redelivery is no longer viable.",
        ),
    ],
    "in_store_and_online_order_conflict": [
        lambda exposure, tier: RecoveryOption(
            "manual_reconciliation_credit",
            "Manual order reconciliation + credit for any shortfall",
            round(exposure * 0.2, 2),
            round(exposure * 0.2, 2) >= settings.high_value_approval_threshold_usd,
            "supervisor",
            "BOPIS/online-in-store mismatch requires manual reconciliation between the two channels.",
        )
    ],
}


def rank_recovery_options(category: str, financial_exposure_usd: float, tier: str) -> list[RecoveryOption]:
    apology = RecoveryOption(
        "apology_status_update",
        "Apology + proactive status update",
        0.0,
        False,
        None,
        "No-cost goodwill gesture, always appropriate alongside (not instead of) a substantive remedy.",
    )
    builders = _CATEGORY_OPTIONS.get(category, [])
    options = [apology] + [b(financial_exposure_usd, tier) for b in builders]

    exceptional = RecoveryOption(
        "exceptional_remedy",
        "Exceptional remedy (loyalty-tier gesture / policy exception)",
        0.0,
        True,
        "supervisor",
        "Out-of-policy exception -- always requires human sign-off regardless of dollar value.",
        is_exceptional=True,
    )
    options.append(exceptional)

    # Deliberately NOT sorted by cost/requires_approval: that would prefer
    # whichever remedy dodges the approval gate, which is backwards -- the
    # gate exists precisely so a high-value or inadequate remedy gets human
    # review, not so the engine can route around it by picking something
    # cheaper. Category order above is authored as primary-remedy-first;
    # only the always-available apology is pinned first and the
    # (always-approval-gated regardless of cost) exceptional option last.
    return options
