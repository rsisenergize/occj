"""Competing-interpretation ("what went wrong") hypothesis generation.

Open-ended (LLM-proposed) per the agreed scope, with two hard guardrails
that keep it auditable:
  1. Every hypothesis must cite at least one real evidence_record_id; any
     citation that doesn't resolve to evidence actually in this case is
     dropped before the hypothesis is stored, and a hypothesis left with no
     valid citations is discarded entirely.
  2. confidence is ALWAYS computed here, deterministically, from the
     resulting EvidenceLink weights -- the LLM's own opinion of how
     confident it is is never stored or trusted.

When no LLM is configured (or a call fails), `_generate_via_template` covers
the same ground using the flag-to-category rules below, so the engine never
just does nothing.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record as record_audit
from app.config import get_settings
from app.db import utcnow
from app.engine.stage import advance_stage
from app.llm.client import LLMUnavailable, chat_json
from app.models.canonical import UncertaintyFlag
from app.models.case import Case
from app.models.enums import (
    ActorType,
    EvidenceRelation,
    HypothesisStatus,
    JourneyStage,
    SourceType,
    UncertaintyFlagType,
)
from app.models.evidence import EvidenceRecord
from app.models.hypothesis import EvidenceLink, Hypothesis

logger = logging.getLogger(__name__)
settings = get_settings()

# Seed context for the LLM -- categories analysts commonly use, NOT an
# enum constraint. The engine will happily store a category the model
# invents if it's grounded in real evidence.
TAXONOMY_SEED = [
    "payment_captured_order_not_created",
    "order_confirmed_fulfillment_never_started",
    "fulfillment_shows_delivered_customer_disputes_receipt",
    "wrong_address_or_failed_delivery_attempt",
    "duplicate_charge",
    "return_received_refund_not_issued",
    "promised_promotion_or_price_not_honored",
    "in_store_and_online_order_conflict",
]

# Source reliability weights for the deterministic confidence calculation --
# transactional systems of record outrank behavioral/self-reported signals.
SOURCE_RELIABILITY = {
    SourceType.ORDER: 1.0,
    SourceType.PAYMENT: 1.0,
    SourceType.STORE_TRANSACTION: 1.0,
    SourceType.FULFILLMENT_UPDATE: 0.9,
    SourceType.RETURN: 0.9,
    SourceType.ITSM_INCIDENT: 0.9,
    SourceType.CONTACT_CENTER_RECORD: 0.7,
    SourceType.WEB_APP_EVENT: 0.5,
}


def _source_weight(rec: EvidenceRecord) -> float:
    return SOURCE_RELIABILITY.get(rec.source_type, 0.6)


async def _current_evidence(session: AsyncSession, case: Case) -> list[EvidenceRecord]:
    result = await session.scalars(
        select(EvidenceRecord).where(
            EvidenceRecord.customer_id == case.customer_id,
            EvidenceRecord.is_superseded.is_(False),
            EvidenceRecord.is_duplicate_of.is_(None),
        )
    )
    return list(result)


async def _open_flags(session: AsyncSession, case: Case) -> list[UncertaintyFlag]:
    result = await session.scalars(
        select(UncertaintyFlag).where(
            UncertaintyFlag.case_id == case.id, UncertaintyFlag.resolved_at.is_(None)
        )
    )
    return list(result)


async def _generate_via_llm(evidence: list[EvidenceRecord], flags: list[UncertaintyFlag]) -> list[dict]:
    evidence_context = [
        {
            "evidence_id": e.id,
            "source_type": e.source_type.value,
            "occurred_at": e.occurred_at.isoformat(),
            "payload": e.payload,
        }
        for e in evidence
    ]
    flag_context = [
        {"flag_type": f.flag_type.value, "description": f.description, "related_evidence_ids": f.related_evidence_ids}
        for f in flags
    ]
    system = (
        "You are an investigator reconstructing why a retail customer's journey "
        "failed across web/app, store, order, fulfillment, payment, contact-centre "
        "and returns systems. Propose 1-4 competing hypotheses for where the "
        "journey broke down. Categories analysts commonly use (not exhaustive, "
        "propose a different one if the evidence clearly warrants it): "
        f"{', '.join(TAXONOMY_SEED)}.\n\n"
        "Every hypothesis MUST cite evidence_id values taken verbatim from the "
        "evidence list you're given -- never invent an id. Respond with strict "
        'JSON: {"hypotheses": [{"category": str, "title": str, "narrative": str, '
        '"supporting_evidence_ids": [str], "weakening_evidence_ids": [str]}]}'
    )
    user = f"Evidence:\n{evidence_context}\n\nOpen uncertainty flags:\n{flag_context}"
    data = await chat_json(system=system, user=user)
    hypotheses = data.get("hypotheses", [])
    for h in hypotheses:
        h["_source"] = "llm"
    return hypotheses


_FLAG_CATEGORY_RULES: list[tuple[UncertaintyFlagType, str, str]] = [
    # (flag_type, description substring to match, category)
    (UncertaintyFlagType.DUPLICATE, "duplicate charge", "duplicate_charge"),
    (UncertaintyFlagType.MISSING, "fulfillment_update after payment", "order_confirmed_fulfillment_never_started"),
    (UncertaintyFlagType.MISSING, "payment after return", "return_received_refund_not_issued"),
    (UncertaintyFlagType.CONTRADICTORY, "disputes receipt", "fulfillment_shows_delivered_customer_disputes_receipt"),
    (UncertaintyFlagType.CONTRADICTORY, "Conflicting fulfillment outcomes", "wrong_address_or_failed_delivery_attempt"),
]


def _generate_via_template(evidence: list[EvidenceRecord], flags: list[UncertaintyFlag]) -> list[dict]:
    specs: list[dict] = []
    for flag in flags:
        category = None
        for flag_type, needle, cat in _FLAG_CATEGORY_RULES:
            if flag.flag_type == flag_type and needle.lower() in flag.description.lower():
                category = cat
                break
        if category is None:
            continue
        specs.append(
            {
                "category": category,
                "title": category.replace("_", " ").capitalize(),
                "narrative": flag.description,
                "supporting_evidence_ids": list(flag.related_evidence_ids),
                "weakening_evidence_ids": [],
                "_source": "template",
            }
        )
    return specs


def _merge_by_category(specs: list[dict]) -> list[dict]:
    """Multiple specs proposing the same category (e.g. two 'missing
    fulfillment' flags for two different payments) become one hypothesis
    with the union of cited evidence, rather than literal duplicates
    competing against themselves."""
    merged: dict[str, dict] = {}
    order: list[str] = []
    for spec in specs:
        category = spec.get("category", "uncategorized")
        if category not in merged:
            merged[category] = {
                "category": category,
                "title": spec.get("title", category.replace("_", " ").capitalize()),
                "narrative": spec.get("narrative", ""),
                "supporting_evidence_ids": list(spec.get("supporting_evidence_ids", [])),
                "weakening_evidence_ids": list(spec.get("weakening_evidence_ids", [])),
                "_source": spec.get("_source", "template"),
            }
            order.append(category)
        else:
            existing = merged[category]
            existing["supporting_evidence_ids"] = list(
                dict.fromkeys(existing["supporting_evidence_ids"] + list(spec.get("supporting_evidence_ids", [])))
            )
            existing["weakening_evidence_ids"] = list(
                dict.fromkeys(existing["weakening_evidence_ids"] + list(spec.get("weakening_evidence_ids", [])))
            )
            if spec.get("narrative") and spec["narrative"] not in existing["narrative"]:
                existing["narrative"] += " " + spec["narrative"]
    return [merged[c] for c in order]


async def compute_confidence(session: AsyncSession, hypothesis_id: str) -> float:
    """Deterministic: weighted_supports / (weighted_supports + weighted_weakens + 1).
    The +1 means a single supporting record never exceeds 0.5 confidence on
    its own -- corroboration from independent, reliable sources is what
    drives confidence up; weakening evidence pulls it back down."""
    links = await session.scalars(select(EvidenceLink).where(EvidenceLink.hypothesis_id == hypothesis_id))
    supports = 0.0
    weakens = 0.0
    for link in links:
        if link.relation == EvidenceRelation.SUPPORTS:
            supports += link.weight
        else:
            weakens += link.weight
    return round(supports / (supports + weakens + 1.0), 4)


async def generate_or_update_hypotheses(session: AsyncSession, case: Case) -> list[Hypothesis]:
    evidence = await _current_evidence(session, case)
    if not evidence:
        return []
    evidence_by_id = {e.id: e for e in evidence}
    flags = await _open_flags(session, case)

    try:
        specs = await _generate_via_llm(evidence, flags)
    except LLMUnavailable as exc:
        logger.info("Hypothesis generation falling back to templates: %s", exc)
        specs = _generate_via_template(evidence, flags)

    if not specs:
        return []
    specs = _merge_by_category(specs)

    previous_active = list(
        await session.scalars(
            select(Hypothesis).where(Hypothesis.case_id == case.id, Hypothesis.status == HypothesisStatus.ACTIVE)
        )
    )
    previous_top_confidence = max((h.confidence for h in previous_active), default=0.0)

    created: list[Hypothesis] = []
    for spec in specs:
        valid_support = [eid for eid in spec.get("supporting_evidence_ids", []) if eid in evidence_by_id]
        valid_weaken = [eid for eid in spec.get("weakening_evidence_ids", []) if eid in evidence_by_id]
        dropped = (set(spec.get("supporting_evidence_ids", [])) | set(spec.get("weakening_evidence_ids", []))) - (
            set(valid_support) | set(valid_weaken)
        )
        if not valid_support:
            continue  # ungrounded hypothesis -- discard, never store

        h = Hypothesis(
            case_id=case.id,
            category=spec.get("category", "uncategorized"),
            title=spec.get("title", spec.get("category", "Hypothesis")),
            narrative=spec.get("narrative", ""),
            generation_context={"source": spec.get("_source", "template"), "dropped_evidence_ids": sorted(dropped)},
            updated_at=utcnow(),
        )
        session.add(h)
        await session.flush()

        for eid in valid_support:
            session.add(
                EvidenceLink(
                    hypothesis_id=h.id,
                    evidence_record_id=eid,
                    relation=EvidenceRelation.SUPPORTS,
                    weight=_source_weight(evidence_by_id[eid]),
                )
            )
        for eid in valid_weaken:
            session.add(
                EvidenceLink(
                    hypothesis_id=h.id,
                    evidence_record_id=eid,
                    relation=EvidenceRelation.WEAKENS,
                    weight=_source_weight(evidence_by_id[eid]),
                )
            )
        await session.flush()

        h.confidence = await compute_confidence(session, h.id)
        created.append(h)

        await record_audit(
            session,
            case_id=case.id,
            entity_type="hypothesis",
            entity_id=h.id,
            event="created",
            actor_type=ActorType.AI_INFERENCE if spec.get("_source") == "llm" else ActorType.SYSTEM,
            actor_id="hypothesis_engine",
            payload={"category": h.category, "confidence": h.confidence, "dropped_evidence_ids": sorted(dropped)},
        )

    if not created:
        return []

    for h in previous_active:
        h.status = HypothesisStatus.SUPERSEDED

    created.sort(key=lambda h: h.confidence, reverse=True)
    top = created[0]
    case.primary_hypothesis_id = top.id
    advance_stage(case, JourneyStage.FAILURE_LOCATED)

    delta = abs(top.confidence - previous_top_confidence)
    if previous_active and delta > settings.reevaluation_confidence_delta:
        case.needs_reevaluation = True
        # A material change deserves a real re-look, not a stage display
        # stuck wherever it happened to be -- jump the case display back to
        # FAILURE_LOCATED even though stage otherwise only moves forward.
        case.stage = JourneyStage.FAILURE_LOCATED
        await record_audit(
            session,
            case_id=case.id,
            entity_type="case",
            entity_id=case.id,
            event="reevaluation_triggered",
            actor_type=ActorType.SYSTEM,
            actor_id="hypothesis_engine",
            payload={
                "previous_top_confidence": previous_top_confidence,
                "new_top_confidence": top.confidence,
                "delta": delta,
            },
        )

    await session.flush()
    return created
