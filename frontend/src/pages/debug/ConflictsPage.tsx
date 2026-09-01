import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { IngestConflictOut } from "../../types";
import { timeAgo } from "../../components/Badges";

export function ConflictsPage() {
  const [conflicts, setConflicts] = useState<IngestConflictOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("unresolved");

  async function load() {
    try {
      const data = await api.get<{ conflicts: IngestConflictOut[] }>(`/debug/conflicts?status=${statusFilter}`);
      setConflicts(data.conflicts);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load conflicts");
    }
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  return (
    <div className="page">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h1 style={{ fontSize: 18, margin: 0 }}>Conflicts</h1>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="unresolved">Unresolved</option>
          <option value="resolved">Resolved</option>
          <option value="">All</option>
        </select>
      </div>
      {error && <div className="card error">{error}</div>}
      {conflicts === null ? (
        <div className="empty-state">Loading...</div>
      ) : conflicts.length === 0 ? (
        <div className="card empty-state">No {statusFilter || ""} conflicts.</div>
      ) : (
        conflicts.map((c) => (
          <div key={c.id} className="card" style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
              <div>
                <strong>{c.fact_type}</strong>{" "}
                <span className={`badge status-${c.resolution_status}`}>{c.resolution_status}</span>
                {c.resolution_rule && <span className="badge">{c.resolution_rule}</span>}
              </div>
              <span className="small muted">{timeAgo(c.detected_at)}</span>
            </div>
            <div className="two-col">
              {c.versions.map((v) => (
                <div key={v.id} className="card" style={{ background: "var(--bg-subtle, #f6f6f6)" }}>
                  <div className="small muted">
                    v{v.version_no} &middot; {v.provenance} &middot; {new Date(v.event_time).toLocaleString()}
                  </div>
                  <pre className="mono small" style={{ whiteSpace: "pre-wrap" }}>
                    {JSON.stringify(v.payload, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
