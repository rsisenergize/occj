from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CustomerOut(ORMModel):
    id: str
    external_customer_id: str
    display_name: str
    email: str | None
    phone: str | None
    tier: str


class CaseOut(ORMModel):
    id: str
    customer_id: str
    order_id: str | None
    trigger_type: str
    status: str
    stage: str
    summary: str | None
    deadline_at: datetime | None
    last_activity_at: datetime
    needs_reevaluation: bool
    primary_hypothesis_id: str | None
    closed_at: datetime | None
    closure_summary: str | None
    created_at: datetime


class CaseCreate(BaseModel):
    external_customer_id: str
    customer_display_name: str
    customer_tier: str = "standard"
    customer_email: str | None = None
    customer_phone: str | None = None
    order_id: str | None = None
    summary: str | None = None


class EvidenceIngest(BaseModel):
    external_customer_id: str
    customer_display_name: str = "Unknown Customer"
    customer_tier: str = "standard"
    source_type: str
    provenance_source: str
    external_ref: str
    occurred_at: datetime
    order_id: str | None = None
    payload: dict
    case_id: str | None = None  # link to an existing case if known


class EvidenceRecordOut(ORMModel):
    id: str
    customer_id: str
    order_id: str | None
    source_type: str
    external_ref: str
    provenance_source: str
    occurred_at: datetime
    ingested_at: datetime
    payload: dict
    actor_type: str
    is_superseded: bool


class CanonicalEventOut(ORMModel):
    id: str
    case_id: str
    evidence_record_id: str
    source_type: str
    effective_at: datetime
    summary: str


class UncertaintyFlagOut(ORMModel):
    id: str
    case_id: str
    flag_type: str
    related_evidence_ids: list[str]
    description: str
    detected_at: datetime
    resolved_at: datetime | None


class EvidenceLinkOut(ORMModel):
    evidence_record_id: str
    relation: str
    weight: float
    note: str | None


class HypothesisOut(ORMModel):
    id: str
    case_id: str
    category: str
    title: str
    narrative: str
    confidence: float
    status: str
    created_at: datetime
    updated_at: datetime
    evidence_links: list[EvidenceLinkOut] = []


class ImpactAssessmentOut(ORMModel):
    id: str
    case_id: str
    hypothesis_id: str | None
    financial_exposure_usd: float
    sla_breach_score: float
    customer_tier_weight: float
    composite_score: float
    explanation: dict
    computed_at: datetime


class ActionRequestOut(ORMModel):
    id: str
    case_id: str
    action_type: str
    target: dict
    rationale: str
    expected_value: float
    status: str
    requires_approval: bool
    decided_at: datetime | None
    created_at: datetime


class ApprovalOut(ORMModel):
    id: str
    action_request_id: str
    required_role: str
    status: str
    decided_by_user_id: str | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime


class ApprovalDecision(BaseModel):
    decision: str  # "approved" | "rejected"
    note: str | None = None


class AuditEntryOut(ORMModel):
    id: str
    case_id: str | None
    entity_type: str
    entity_id: str
    event: str
    actor_type: str
    actor_id: str | None
    payload: dict
    occurred_at: datetime


class CaseDetailOut(BaseModel):
    case: CaseOut
    customer: CustomerOut
    timeline: list[CanonicalEventOut]
    uncertainty_flags: list[UncertaintyFlagOut]
    hypotheses: list[HypothesisOut]
    latest_impact: ImpactAssessmentOut | None
    actions: list[ActionRequestOut]
