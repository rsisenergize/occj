from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import IdMixin, TimestampMixin


class ImpactAssessment(Base, IdMixin, TimestampMixin):
    """Explainable urgency/expected-value score feeding the NBA engine.

    Every component is stored individually (not just the composite) so the
    audit trail and UI can show *why* a case is urgent, not just a number.
    """

    __tablename__ = "impact_assessments"

    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    hypothesis_id: Mapped[str | None] = mapped_column(ForeignKey("hypotheses.id"), nullable=True)

    financial_exposure_usd: Mapped[float] = mapped_column(Float, default=0.0)
    sla_breach_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    customer_tier_weight: Mapped[float] = mapped_column(Float, default=1.0)
    composite_score: Mapped[float] = mapped_column(Float, default=0.0)

    explanation: Mapped[dict] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
