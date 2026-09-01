import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { IngestEventOut } from "../../types";
import { timeAgo } from "../../components/Badges";

const SOURCES = ["webapp", "pos", "oms", "wms", "payments", "cc", "returns"];

export function LiveFeedPage() {
  const [events, setEvents] = useState<IngestEventOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [selected, setSelected] = useState<IngestEventOut | null>(null);

  async function load() {
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (source) params.set("source", source);
      if (customerId) params.set("customer_id", customerId);
      const data = await api.get<{ events: IngestEventOut[] }>(`/debug/events/recent?${params}`);
      setEvents(data.events);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load events");
    }
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, customerId]);

  return (
    <div className="page">
      <h1 style={{ fontSize: 18, margin: "0 0 12px" }}>Live Ingestion Feed</h1>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">All sources</option>
          {SOURCES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <input
          placeholder="Filter by customer_id..."
          value={customerId}
          onChange={(e) => setCustomerId(e.target.value)}
        />
      </div>
      {error && <div className="card error">{error}</div>}
      <div style={{ display: "flex", gap: 12 }}>
        <div className="card" style={{ padding: 0, flex: selected ? 2 : 1 }}>
          {events === null ? (
            <div className="empty-state" style={{ padding: 16 }}>
              Loading...
            </div>
          ) : events.length === 0 ? (
            <div className="empty-state" style={{ padding: 16 }}>
              No events yet. Fire a webhook at one of the /ingest/&lt;source&gt; endpoints.
            </div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Source</th>
                  <th>Fact type</th>
                  <th>Order</th>
                  <th>v</th>
                  <th>Status/Kind</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id} className="clickable" onClick={() => setSelected(e)}>
                    <td className="small muted">{timeAgo(e.created_at)}</td>
                    <td>
                      <span className="badge">{e.source_system ?? e.provenance}</span>
                    </td>
                    <td>{e.fact_type ?? "order_status"}</td>
                    <td className="mono small">{e.order_id ?? "-"}</td>
                    <td className="small muted">{e.version_no}</td>
                    <td className="small">{e.status ?? e.kind}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {selected && (
          <div className="card" style={{ flex: 1 }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <strong>Event detail</strong>
              <button onClick={() => setSelected(null)}>Close</button>
            </div>
            <pre className="mono small" style={{ whiteSpace: "pre-wrap", marginTop: 8 }}>
              {JSON.stringify(selected, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
