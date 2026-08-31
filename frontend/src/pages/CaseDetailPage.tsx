import { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api/client";
import type { AuditEntryOut, CaseDetailOut } from "../types";
import { StageTracker } from "../components/StageTracker";
import { TimelinePanel } from "../components/TimelinePanel";
import { HypothesesPanel } from "../components/HypothesesPanel";
import { ImpactPanel } from "../components/ImpactPanel";
import { ActionsPanel } from "../components/ActionsPanel";
import { AuditTrailPanel } from "../components/AuditTrailPanel";
import { StatusBadge } from "../components/Badges";
import { useAuth } from "../auth/AuthContext";

export function CaseDetailPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const { user } = useAuth();
  const [detail, setDetail] = useState<CaseDetailOut | null>(null);
  const [trail, setTrail] = useState<AuditEntryOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [advancing, setAdvancing] = useState(false);

  const load = useCallback(async () => {
    if (!caseId) return;
    try {
      const [d, t] = await Promise.all([
        api.get<CaseDetailOut>(`/cases/${caseId}`),
        api.get<AuditEntryOut[]>(`/cases/${caseId}/audit`),
      ]);
      setDetail(d);
      setTrail(t);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load case");
    }
  }, [caseId]);

  useEffect(() => {
    load();
    const id = setInterval(load, 8000); // polling stand-in for Supabase Realtime -- see README
    return () => clearInterval(id);
  }, [load]);

  async function advance() {
    if (!caseId) return;
    setAdvancing(true);
    try {
      await api.post(`/cases/${caseId}/advance`);
      await load();
    } finally {
      setAdvancing(false);
    }
  }

  if (error) return <div className="page"><div className="card">{error}</div></div>;
  if (!detail) return <div className="page">Loading...</div>;

  const { case: c, customer, timeline, uncertainty_flags, hypotheses, latest_impact, actions, approvals } = detail;
  const canAdvance = user && (user.role === "agent" || user.role === "supervisor" || user.role === "admin");

  return (
    <div className="page">
      <Link to="/cases" className="small">&larr; All cases</Link>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", margin: "8px 0 4px" }}>
        <div>
          <h1 style={{ fontSize: 18, margin: 0 }}>
            {customer.display_name} <span className="muted small">({customer.tier})</span>
          </h1>
          <div className="small muted">
            Order {c.order_id || "-"} &middot; opened via {c.trigger_type.replace(/_/g, " ")} &middot; case{" "}
            {c.id.slice(0, 8)}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <StatusBadge status={c.status} />
          {canAdvance && c.status !== "closed" && (
            <button onClick={advance} disabled={advancing}>
              {advancing ? "Advancing..." : "Advance case"}
            </button>
          )}
        </div>
      </div>
      <StageTracker stage={c.stage} />
      {c.summary && <div className="card small muted">{c.summary}</div>}
      {c.closure_summary && (
        <div className="card" style={{ background: "var(--success-soft)" }}>
          <strong>Outcome:</strong> {c.closure_summary}
        </div>
      )}

      <div className="two-col">
        <div>
          <TimelinePanel events={timeline} flags={uncertainty_flags} />
          <ActionsPanel actions={actions} approvals={approvals} onChanged={load} />
          <AuditTrailPanel caseId={c.id} trail={trail} />
        </div>
        <div>
          <HypothesesPanel hypotheses={hypotheses} primaryId={c.primary_hypothesis_id} />
          <ImpactPanel impact={latest_impact} />
        </div>
      </div>
    </div>
  );
}
