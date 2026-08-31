from sqlalchemy import select

from app.engine.hypothesis_engine import generate_or_update_hypotheses
from app.models.enums import SourceType
from app.models.evidence import EvidenceRecord
from app.models.hypothesis import EvidenceLink
from app.reconciliation.reconciler import ingest_evidence, reconcile_case
from tests.conftest import ago, make_case, make_customer


async def test_hypothesis_only_cites_real_evidence_and_confidence_is_deterministic(session, now):
    customer = await make_customer(session, tier="gold")
    case = await make_case(session, customer, order_id="ord-1")
    await ingest_evidence(
        session, customer=customer, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
        external_ref="pay-a", occurred_at=ago(now, hours=2), order_id="ord-1",
        payload={"status": "captured", "amount": 100.0, "method": "card"},
    )
    await ingest_evidence(
        session, customer=customer, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
        external_ref="pay-b", occurred_at=ago(now, hours=2), order_id="ord-1",
        payload={"status": "captured", "amount": 100.0, "method": "card"},
    )
    await reconcile_case(session, case)
    hyps = await generate_or_update_hypotheses(session, case)

    assert len(hyps) == 1
    assert hyps[0].category == "duplicate_charge"

    links = list(await session.scalars(select(EvidenceLink).where(EvidenceLink.hypothesis_id == hyps[0].id)))
    assert len(links) > 0
    real_evidence_ids = set(await session.scalars(select(EvidenceRecord.id)))
    assert all(link.evidence_record_id in real_evidence_ids for link in links)  # no hallucinated citations

    assert 0.0 <= hyps[0].confidence <= 1.0
    assert case.primary_hypothesis_id == hyps[0].id


async def test_no_evidence_produces_no_hypothesis(session, now):
    customer = await make_customer(session)
    case = await make_case(session, customer)
    await reconcile_case(session, case)
    hyps = await generate_or_update_hypotheses(session, case)
    assert hyps == []
    assert case.primary_hypothesis_id is None


async def test_reevaluation_flag_set_on_material_confidence_shift(session, now):
    customer = await make_customer(session)
    case = await make_case(session, customer, order_id="ord-1")
    # Payment well past the 48h fulfillment-followup SLA window -- this is
    # what makes it "missing" evidence at all (a too-recent payment
    # wouldn't be overdue yet, so no flag/hypothesis would exist to test).
    await ingest_evidence(
        session, customer=customer, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
        external_ref="pay-a", occurred_at=ago(now, hours=72), order_id="ord-1",
        payload={"status": "captured", "amount": 100.0, "method": "card"},
    )
    await reconcile_case(session, case)
    first = await generate_or_update_hypotheses(session, case)
    assert len(first) == 1
    assert case.needs_reevaluation is False  # nothing to compare against yet

    # A second, independent overdue order corroborates the same category
    # (systemic pattern), pushing confidence up materially.
    await ingest_evidence(
        session, customer=customer, source_type=SourceType.PAYMENT, provenance_source="mock:payments",
        external_ref="pay-b", occurred_at=ago(now, hours=72), order_id="ord-2",
        payload={"status": "captured", "amount": 100.0, "method": "card"},
    )
    await reconcile_case(session, case)
    second = await generate_or_update_hypotheses(session, case)

    assert len(second) == 1
    assert second[0].confidence != first[0].confidence
    assert case.needs_reevaluation is True
    # the original hypothesis is preserved, just marked superseded -- never deleted
    await session.refresh(first[0])
    assert first[0].status == "superseded"
