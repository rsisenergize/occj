from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import EvidenceRelation, HypothesisStatus
from app.models.mixins import IdMixin, TimestampMixin, enum_column


class Hypothesis(Base, IdMixin, TimestampMixin):
    """A competing interpretation of where the journey failed.

    category/title/narrative are LLM-proposed and open-ended (per the agreed
    scope) -- the 8-item starter taxonomy is seed context in the generation
    prompt, not an enum constraint. confidence is NEVER set by the LLM: it is
    always recomputed deterministically from this hypothesis's EvidenceLink
    rows (see app/engine/hypothesis_engine.py), which is what keeps an
    open-ended hypothesis auditable.
    """

    __tablename__ = "hypotheses"

    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)

    category: Mapped[str] = mapped_column(String(128))  # free text, taxonomy-seeded
    title: Mapped[str] = mapped_column(String(256))
    narrative: Mapped[str] = mapped_column(String(4096))

    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[HypothesisStatus] = enum_column(HypothesisStatus, default=HypothesisStatus.ACTIVE)

    # Raw LLM generation context, stored for audit replay (what evidence/prompt
    # produced this hypothesis, and the model's own citations before validation
    # dropped any that didn't resolve to a real evidence id).
    generation_context: Mapped[dict] = mapped_column(JSON, default=dict)

    superseded_by_id: Mapped[str | None] = mapped_column(ForeignKey("hypotheses.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=None)


class EvidenceLink(Base, IdMixin, TimestampMixin):
    """Links a Hypothesis to an EvidenceRecord it cites, with the relation
    (supports/weakens) and the weight that feeds the deterministic confidence
    calculation. Every citation here was validated to reference a real
    evidence_record_id at generation time -- the anti-hallucination guardrail."""

    __tablename__ = "evidence_links"

    hypothesis_id: Mapped[str] = mapped_column(ForeignKey("hypotheses.id"), index=True)
    evidence_record_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"), index=True)

    relation: Mapped[EvidenceRelation] = enum_column(EvidenceRelation)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
