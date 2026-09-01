export interface CustomerOut {
  id: string;
  external_customer_id: string;
  display_name: string;
  email: string | null;
  phone: string | null;
  tier: string;
}

export interface CaseOut {
  id: string;
  customer_id: string;
  order_id: string | null;
  trigger_type: string;
  status: string;
  stage: string;
  summary: string | null;
  deadline_at: string | null;
  last_activity_at: string;
  needs_reevaluation: boolean;
  primary_hypothesis_id: string | null;
  closed_at: string | null;
  closure_summary: string | null;
  created_at: string;
}

export interface CanonicalEventOut {
  id: string;
  case_id: string;
  evidence_record_id: string;
  source_type: string;
  effective_at: string;
  summary: string;
}

export interface UncertaintyFlagOut {
  id: string;
  case_id: string;
  flag_type: "missing" | "stale" | "duplicate" | "contradictory";
  related_evidence_ids: string[];
  description: string;
  detected_at: string;
  resolved_at: string | null;
}

export interface EvidenceLinkOut {
  evidence_record_id: string;
  relation: "supports" | "weakens";
  weight: number;
  note: string | null;
}

export interface HypothesisOut {
  id: string;
  case_id: string;
  category: string;
  title: string;
  narrative: string;
  confidence: number;
  status: string;
  created_at: string;
  updated_at: string;
  evidence_links: EvidenceLinkOut[];
}

export interface ImpactAssessmentOut {
  id: string;
  case_id: string;
  hypothesis_id: string | null;
  financial_exposure_usd: number;
  sla_breach_score: number;
  customer_tier_weight: number;
  composite_score: number;
  explanation: Record<string, unknown>;
  computed_at: string;
}

export interface ActionRequestOut {
  id: string;
  case_id: string;
  action_type: string;
  target: Record<string, any>;
  rationale: string;
  expected_value: number;
  status: string;
  requires_approval: boolean;
  decided_at: string | null;
  created_at: string;
}

export interface ApprovalOut {
  id: string;
  action_request_id: string;
  case_id: string | null;
  required_role: string;
  status: string;
  decided_by_user_id: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}

export interface AuditEntryOut {
  id: string;
  case_id: string | null;
  entity_type: string;
  entity_id: string;
  event: string;
  actor_type: string;
  actor_id: string | null;
  payload: Record<string, unknown>;
  occurred_at: string;
}

export interface CaseDetailOut {
  case: CaseOut;
  customer: CustomerOut;
  timeline: CanonicalEventOut[];
  uncertainty_flags: UncertaintyFlagOut[];
  hypotheses: HypothesisOut[];
  latest_impact: ImpactAssessmentOut | null;
  actions: ActionRequestOut[];
  approvals: ApprovalOut[];
}

export interface ReplayState {
  case_id: string;
  as_of: string;
  stage: string;
  hypotheses_known_at_this_point: Record<string, any>;
  actions_known_at_this_point: Record<string, any>;
  approvals_known_at_this_point: Record<string, any>;
  evidence_events_count: number;
  audit_entry_count: number;
  trail: AuditEntryOut[];
}

export interface CurrentUser {
  id: string;
  username: string;
  role: string;
  display_name: string;
}

// --- Ingestion pipeline v2 debug UI (app/ingest/debug_routes.py) ---

export interface IngestEventOut {
  id: string;
  kind: "log_version" | "order_version";
  version_no: number;
  payload: Record<string, unknown>;
  event_time: string;
  received_time: string;
  timezone: string;
  provenance: string;
  created_at: string;
  status?: string; // order_version only
  fact_type?: string; // log_version only
  source_system?: string; // log_version only
  log_id?: string; // log_version only
  order_id?: string | null;
}

export interface IngestConflictOut {
  id: string;
  timeline_id: string;
  fact_type: string;
  resolution_status: "unresolved" | "resolved";
  resolution_rule: string | null;
  detected_at: string;
  versions: IngestEventOut[];
}

export interface IngestOrderOut {
  id: string;
  order_ref: string;
  versions: IngestEventOut[];
}

export interface IngestLogOut {
  id: string;
  fact_type: string;
  source_system: string;
  order_id: string | null;
  versions: IngestEventOut[];
}

export interface IngestTimelineOut {
  id: string;
  status: string;
  created_at: string;
  orders: IngestOrderOut[];
  logs: IngestLogOut[];
  conflicts: {
    id: string;
    fact_type: string;
    resolution_status: string;
    resolution_rule: string | null;
    detected_at: string;
  }[];
}

export interface IngestTimelineExplorerOut {
  customer: { id: string; external_customer_id: string; display_name: string };
  timelines: IngestTimelineOut[];
}

export interface IngestSourceHealth {
  last_seen: string | null;
  events_1h: number;
  events_24h: number;
}

export interface IngestHealthSummaryOut {
  sources: Record<string, IngestSourceHealth>;
  dead_letter_count: number;
  outbox_pending_count: number;
}

export interface IngestDeadLetterOut {
  id: string;
  raw_event: Record<string, unknown>;
  error_reason: string;
  attempt_count: number;
  failed_at: string;
}
