"""Pluggable conflict-RESOLUTION strategies (distinct from materiality.py's
conflict-DETECTION rules). A strategy decides whether an already-detected
conflict can be auto-resolved -- and if so, by what rule -- without ever
deleting or hiding the losing version, per spec §4 step 6: "Do NOT
auto-resolve unless a defined precedence rule exists ... the conflicting
record stays visible, never deleted."
"""
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ConflictContext:
    fact_type: str
    existing_provenance: str
    existing_payload: dict[str, Any]
    new_provenance: str
    new_payload: dict[str, Any]


@dataclass(frozen=True)
class ResolutionOutcome:
    rule_name: str
    note: str


class ConflictResolutionStrategy(Protocol):
    def applies_to(self, fact_type: str) -> bool: ...

    def resolve(self, ctx: ConflictContext) -> ResolutionOutcome | None:
        """Return a ResolutionOutcome if this strategy can resolve the
        conflict, or None to leave it unresolved (falls through to the
        next strategy, or stays open for human review if none resolve it)."""
        ...


class TrustedSourcePrecedenceStrategy:
    """Concrete example strategy required by spec §4 step 6: for
    payment_event conflicts specifically, the payments gateway's own
    record of the settled amount is authoritative over any other source
    (e.g. a contact-centre transcript claiming a different amount). The
    losing record is never deleted -- both LogVersion rows remain; only
    the Conflict row's resolution_status/resolution_rule change."""

    TRUSTED_SOURCE = "payments"
    APPLIES_TO_FACT_TYPES = frozenset({"payment_event"})

    def applies_to(self, fact_type: str) -> bool:
        return fact_type in self.APPLIES_TO_FACT_TYPES

    def resolve(self, ctx: ConflictContext) -> ResolutionOutcome | None:
        if self.TRUSTED_SOURCE not in (ctx.existing_provenance, ctx.new_provenance):
            return None  # neither side is the trusted source -- can't resolve
        trusted_payload = ctx.new_payload if ctx.new_provenance == self.TRUSTED_SOURCE else ctx.existing_payload
        return ResolutionOutcome(
            rule_name="trusted_source_precedence",
            note=(
                f"payments gateway record (amount={trusted_payload.get('amount')}) takes precedence "
                f"for the settled amount; the conflicting record from '{ctx.new_provenance if ctx.existing_provenance == self.TRUSTED_SOURCE else ctx.existing_provenance}' "
                f"is retained, not deleted."
            ),
        )


DEFAULT_STRATEGIES: list[ConflictResolutionStrategy] = [TrustedSourcePrecedenceStrategy()]


def try_resolve(
    ctx: ConflictContext, strategies: list[ConflictResolutionStrategy] | None = None
) -> ResolutionOutcome | None:
    for strategy in (strategies if strategies is not None else DEFAULT_STRATEGIES):
        if strategy.applies_to(ctx.fact_type):
            outcome = strategy.resolve(ctx)
            if outcome is not None:
                return outcome
    return None
