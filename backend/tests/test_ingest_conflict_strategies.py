from app.ingest.conflict_strategies import ConflictContext, try_resolve


def test_trusted_source_precedence_resolves_when_payments_involved():
    ctx = ConflictContext(
        fact_type="payment_event",
        existing_provenance="payments",
        existing_payload={"amount": 49.99},
        new_provenance="cc",
        new_payload={"amount": 59.99},
    )
    outcome = try_resolve(ctx)
    assert outcome is not None
    assert outcome.rule_name == "trusted_source_precedence"
    assert "49.99" in outcome.note  # the trusted (payments) side's amount


def test_no_strategy_resolves_when_neither_side_is_trusted():
    ctx = ConflictContext(
        fact_type="payment_event",
        existing_provenance="cc",
        existing_payload={"amount": 49.99},
        new_provenance="webapp",
        new_payload={"amount": 59.99},
    )
    assert try_resolve(ctx) is None


def test_no_strategy_applies_to_unhandled_fact_type():
    ctx = ConflictContext(
        fact_type="order_status", existing_provenance="oms", existing_payload={}, new_provenance="oms", new_payload={}
    )
    assert try_resolve(ctx) is None
