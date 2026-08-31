"""Enumerations shared across the domain model.

These are deliberately plain str Enums (not open text) wherever a
downstream engine needs to branch on the value deterministically. Where the
brief calls for open-ended content (hypothesis category, action rationale)
the field is free text instead -- see the models for which is which.
"""
from enum import StrEnum


class ActorType(StrEnum):
    """Separates recorded fact from AI inference from human/automated action,
    per the brief's audit requirement."""

    SYSTEM = "system"
    AI_INFERENCE = "ai_inference"
    HUMAN_INPUT = "human_input"
    AUTOMATED_ACTION = "automated_action"
    HUMAN_DECISION = "human_decision"


class SourceType(StrEnum):
    WEB_APP_EVENT = "web_app_event"
    STORE_TRANSACTION = "store_transaction"
    ORDER = "order"
    FULFILLMENT_UPDATE = "fulfillment_update"
    PAYMENT = "payment"
    CONTACT_CENTER_RECORD = "contact_center_record"
    RETURN = "return"
    ITSM_INCIDENT = "itsm_incident"


class CaseTriggerType(StrEnum):
    CUSTOMER_CONTACT = "customer_contact"
    SYSTEM_DETECTED = "system_detected"
    MANUAL = "manual"


class CaseStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    PENDING_EVIDENCE = "pending_evidence"
    PENDING_APPROVAL = "pending_approval"
    ACTION_IN_PROGRESS = "action_in_progress"
    PENDING_CUSTOMER_UPDATE = "pending_customer_update"
    CLOSED = "closed"
    REOPENED = "reopened"


class JourneyStage(StrEnum):
    """The 9-stage reference journey. Informational/display -- the case can
    move non-linearly (e.g. re-evaluation can send it back a stage), the NBA
    engine does not treat this as a fixed pipeline."""

    ISSUE_REPORTED = "issue_reported"
    JOURNEY_ASSEMBLED = "journey_assembled"
    FAILURE_LOCATED = "failure_located"
    EVIDENCE_CHECKED = "evidence_checked"
    IMPACT_ASSESSED = "impact_assessed"
    RECOVERY_OPTIONS_RANKED = "recovery_options_ranked"
    ACTIONS_COORDINATED = "actions_coordinated"
    CUSTOMER_UPDATED = "customer_updated"
    OUTCOME_RETAINED = "outcome_retained"


class UncertaintyFlagType(StrEnum):
    MISSING = "missing"
    STALE = "stale"
    DUPLICATE = "duplicate"
    CONTRADICTORY = "contradictory"


class HypothesisStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class EvidenceRelation(StrEnum):
    SUPPORTS = "supports"
    WEAKENS = "weakens"


class ActionType(StrEnum):
    """What the action DOES when executed. "Proposed" vs "approved" vs
    "executing" is ActionStatus, not a separate type -- a recovery action is
    always EXECUTE_RECOVERY, just starting from status=PROPOSED or
    PENDING_APPROVAL depending on whether it clears the approval threshold."""

    REQUEST_EVIDENCE = "request_evidence"
    RUN_ANALYSIS = "run_analysis"
    EXECUTE_RECOVERY = "execute_recovery"
    ESCALATE_ITSM = "escalate_itsm"
    NOTIFY_CUSTOMER = "notify_customer"
    CLOSE_CASE = "close_case"


class ActionStatus(StrEnum):
    PROPOSED = "proposed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class UserRole(StrEnum):
    AGENT = "agent"
    SUPERVISOR = "supervisor"
    FINANCE_APPROVER = "finance_approver"
    ADMIN = "admin"


class ToolExecutionStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
