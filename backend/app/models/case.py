from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import CaseStatus, CaseTriggerType, JourneyStage
from app.models.mixins import IdMixin, TimestampMixin, enum_column


class Customer(Base, IdMixin, TimestampMixin):
    """Simplified identity: one canonical customer_id is the join key across
    every source system (per the agreed scope -- no fuzzy identity
    resolution). order_id is the secondary join key used within a customer's
    evidence set to group a single transactional chain."""

    __tablename__ = "customers"

    external_customer_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tier: Mapped[str] = mapped_column(String(32), default="standard")  # standard/silver/gold/platinum


class Case(Base, IdMixin, TimestampMixin):
    """The investigation aggregate. Deliberately thin -- most state lives in
    the linked EvidenceRecord/Hypothesis/ActionRequest/AuditEntry rows so the
    case itself never needs a schema change when we learn more about it."""

    __tablename__ = "cases"

    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    trigger_type: Mapped[CaseTriggerType] = enum_column(CaseTriggerType)
    opened_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    status: Mapped[CaseStatus] = enum_column(CaseStatus, default=CaseStatus.OPEN)
    stage: Mapped[JourneyStage] = enum_column(JourneyStage, default=JourneyStage.ISSUE_REPORTED)

    summary: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=None)

    # Set true whenever new/corrected evidence shifts the leading hypothesis's
    # confidence by more than settings.reevaluation_confidence_delta -- the
    # NBA engine checks this before ever trusting a cached conclusion.
    needs_reevaluation: Mapped[bool] = mapped_column(default=False)

    primary_hypothesis_id: Mapped[str | None] = mapped_column(
        ForeignKey("hypotheses.id", use_alter=True), nullable=True
    )

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closure_summary: Mapped[str | None] = mapped_column(String(2048), nullable=True)
