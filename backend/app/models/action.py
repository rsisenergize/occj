from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import ActionStatus, ActionType, ApprovalStatus, ToolExecutionStatus
from app.models.mixins import IdMixin, TimestampMixin, enum_column


class ActionRequest(Base, IdMixin, TimestampMixin):
    """The NBA engine's chosen next step. idempotency_key is unique and is
    what prevents duplicate requests/transactions/external actions when a
    re-evaluation or a retry re-runs the engine."""

    __tablename__ = "action_requests"

    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    action_type: Mapped[ActionType] = enum_column(ActionType)

    target: Mapped[dict] = mapped_column(JSON)  # what evidence/recovery option/connector call this refers to
    rationale: Mapped[str] = mapped_column(String(2048))
    expected_value: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[ActionStatus] = enum_column(ActionStatus, default=ActionStatus.PROPOSED)
    requires_approval: Mapped[bool] = mapped_column(default=False)

    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)

    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Approval(Base, IdMixin, TimestampMixin):
    __tablename__ = "approvals"

    action_request_id: Mapped[str] = mapped_column(ForeignKey("action_requests.id"), index=True)
    required_role: Mapped[str] = mapped_column(String(32))

    status: Mapped[ApprovalStatus] = enum_column(ApprovalStatus, default=ApprovalStatus.PENDING)
    decided_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class ToolExecution(Base, IdMixin, TimestampMixin):
    """One attempt to execute an ActionRequest against a connector (real or
    mock). Multiple rows per ActionRequest on retry -- attempt_number orders
    them, idempotency_key on the parent ActionRequest is what stops the
    *external* system from double-processing even if we retry."""

    __tablename__ = "tool_executions"

    action_request_id: Mapped[str] = mapped_column(ForeignKey("action_requests.id"), index=True)
    connector: Mapped[str] = mapped_column(String(64))  # "freshdesk" | "freshservice" | "mock:payments" | ...
    attempt_number: Mapped[int] = mapped_column(default=1)

    status: Mapped[ToolExecutionStatus] = enum_column(ToolExecutionStatus, default=ToolExecutionStatus.PENDING)
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    response_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
