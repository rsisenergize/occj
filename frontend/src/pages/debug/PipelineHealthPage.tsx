import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { IngestDeadLetterOut, IngestHealthSummaryOut } from "../../types";
import { timeAgo } from "../../components/Badges";

const STALE_MINUTES = 60;

export function PipelineHealthPage() {
  const [health, setHealth] = useState<IngestHealthSummaryOut | null>(null);
  const [deadLetters, setDeadLetters] = useState<IngestDeadLetterOut[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [h, dl] = await Promise.all([
        api.get<IngestHealthSummaryOut>("/debug/health/summary"),
        api.get<{ dead_letters: IngestDeadLetterOut[] }>("/debug/dead-letters"),
      ]);
      setHealth(h);
      setDeadLetters(dl.dead_letters);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load health");
    }
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  function isStale(lastSeen: string | null): boolean {
    if (!lastSeen) return false; // never seen -- not "stale", just unused
    return Date.now() - new Date(lastSeen).getTime() > STALE_MINUTES * 60_000;
  }

  return (
    <div className="page">
      <h1 style={{ fontSize: 18, margin: "0 0 12px" }}>Pipeline Health</h1>
      {error && <div className="card error">{error}</div>}
      {health && (
        <>
          <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
            <div className="card" style={{ minWidth: 160 }}>
              <div className="small muted">Dead letters</div>
              <div style={{ fontSize: 24 }}>{health.dead_letter_count}</div>
            </div>
            <div className="card" style={{ minWidth: 160 }}>
              <div className="small muted">Outbox pending</div>
              <div style={{ fontSize: 24 }}>{health.outbox_pending_count}</div>
            </div>
          </div>

          <div className="card" style={{ padding: 0, marginBottom: 16 }}>
            <table>
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Last seen</th>
                  <th>Events (1h)</th>
                  <th>Events (24h)</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(health.sources).map(([source, s]) => (
                  <tr key={source}>
                    <td>
                      <span className="badge">{source}</span>
                    </td>
                    <td className={isStale(s.last_seen) ? "flag-contradictory" : "small muted"}>
                      {s.last_seen ? timeAgo(s.last_seen) : "never"}
                      {isStale(s.last_seen) && " ⚠ stale"}
                    </td>
                    <td>{s.events_1h}</td>
                    <td>{s.events_24h}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2 style={{ fontSize: 16 }}>Dead letters</h2>
      {deadLetters.length === 0 ? (
        <div className="card empty-state">None -- nothing has exhausted retries.</div>
      ) : (
        deadLetters.map((dl) => (
          <div key={dl.id} className="card" style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <strong className="flag-contradictory">{dl.error_reason}</strong>
              <span className="small muted">{timeAgo(dl.failed_at)}</span>
            </div>
            <div className="small muted">{dl.attempt_count} attempts</div>
            <pre className="mono small" style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(dl.raw_event, null, 2)}
            </pre>
          </div>
        ))
      )}
    </div>
  );
}
