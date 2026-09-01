import { useState } from "react";
import { api } from "../../api/client";
import type { IngestTimelineExplorerOut } from "../../types";

export function TimelineExplorerPage() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<IngestTimelineExplorerOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function search() {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<IngestTimelineExplorerOut>(`/debug/timeline/${encodeURIComponent(query.trim())}`);
      setResult(data);
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Not found");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <h1 style={{ fontSize: 18, margin: "0 0 12px" }}>Timeline Explorer</h1>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <input
          placeholder="customer_id or order_ref..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()}
          style={{ flex: 1 }}
        />
        <button onClick={search} disabled={loading}>
          {loading ? "Searching..." : "Search"}
        </button>
      </div>
      {error && <div className="card error">{error}</div>}
      {result && (
        <div>
          <div className="card" style={{ marginBottom: 12 }}>
            <strong>{result.customer.display_name}</strong>{" "}
            <span className="mono small muted">{result.customer.external_customer_id}</span>
          </div>
          {result.timelines.map((tl) => (
            <div key={tl.id} className="card" style={{ marginBottom: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                <span className="mono small">{tl.id.slice(0, 8)}</span>
                <span className={`badge status-${tl.status}`}>{tl.status}</span>
              </div>

              {tl.conflicts.length > 0 && (
                <div className="uncertainty-banner" style={{ marginBottom: 8 }}>
                  {tl.conflicts.length} conflict(s):{" "}
                  {tl.conflicts.map((c) => (
                    <span key={c.id} className="badge flag-contradictory" style={{ marginRight: 4 }}>
                      {c.fact_type}: {c.resolution_status}
                      {c.resolution_rule ? ` (${c.resolution_rule})` : ""}
                    </span>
                  ))}
                </div>
              )}

              {tl.orders.map((o) => (
                <div key={o.id} style={{ marginBottom: 8 }}>
                  <div className="small muted">Order {o.order_ref}</div>
                  {o.versions.map((v) => (
                    <div key={v.id} className="timeline-item">
                      <span className="mono small">v{v.version_no}</span> {v.status} via {v.provenance}{" "}
                      <span className="small muted">{new Date(v.event_time).toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              ))}

              {tl.logs.map((log) => (
                <div key={log.id} style={{ marginBottom: 8 }}>
                  <div className="small muted">
                    {log.fact_type} <span className="badge">{log.source_system}</span>
                  </div>
                  {log.versions.map((v) => (
                    <div key={v.id} className="timeline-item">
                      <span className="mono small">v{v.version_no}</span>{" "}
                      <span className="small">{JSON.stringify(v.payload)}</span>{" "}
                      <span className="small muted">{new Date(v.event_time).toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
