import { useState } from "react";
import { api } from "../api/client";
import type { AuditEntryOut, ReplayState } from "../types";

export function AuditTrailPanel({ caseId, trail }: { caseId: string; trail: AuditEntryOut[] }) {
  const [expanded, setExpanded] = useState(false);
  const [replayAt, setReplayAt] = useState("");
  const [replay, setReplay] = useState<ReplayState | null>(null);
  const [loadingReplay, setLoadingReplay] = useState(false);

  async function runReplay() {
    setLoadingReplay(true);
    try {
      const qs = replayAt ? `?as_of=${encodeURIComponent(new Date(replayAt).toISOString())}` : "";
      const state = await api.get<ReplayState>(`/cases/${caseId}/replay${qs}`);
      setReplay(state);
    } finally {
      setLoadingReplay(false);
    }
  }

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>Audit trail</h2>
        <button onClick={() => setExpanded(!expanded)}>{expanded ? "Collapse" : `Show (${trail.length})`}</button>
      </div>
      {expanded && (
        <>
          <div style={{ display: "flex", gap: 8, margin: "12px 0", alignItems: "center" }}>
            <label className="small muted">Replay state as of:</label>
            <input type="datetime-local" value={replayAt} onChange={(e) => setReplayAt(e.target.value)} />
            <button onClick={runReplay} disabled={loadingReplay}>
              {loadingReplay ? "Loading..." : "Replay"}
            </button>
          </div>
          {replay && (
            <div
              className="small"
              style={{ background: "var(--accent-soft)", padding: 10, borderRadius: 6, marginBottom: 12 }}
            >
              As of {new Date(replay.as_of).toLocaleString()}: stage was <strong>{replay.stage}</strong>,{" "}
              {Object.keys(replay.hypotheses_known_at_this_point).length} hypothesis(es) known,{" "}
              {Object.keys(replay.actions_known_at_this_point).length} action(s) known,{" "}
              {replay.audit_entry_count} audit entries so far.
            </div>
          )}
          <div style={{ maxHeight: 400, overflowY: "auto" }}>
            {trail.map((e) => (
              <div key={e.id} className="timeline-item">
                <div className="dot" style={{ background: actorColor(e.actor_type) }} />
                <div style={{ flex: 1 }}>
                  <div>
                    <strong>{e.entity_type}</strong> &middot; {e.event}
                  </div>
                  <div className="meta">
                    {new Date(e.occurred_at).toLocaleString()} &middot; actor: {e.actor_type}
                    {e.actor_id ? ` (${e.actor_id})` : ""}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function actorColor(actorType: string): string {
  switch (actorType) {
    case "ai_inference":
      return "#9b59b6";
    case "human_decision":
      return "#1f8a4c";
    case "human_input":
      return "#2f5fdb";
    case "automated_action":
      return "#b8860b";
    default:
      return "#6b7280";
  }
}
