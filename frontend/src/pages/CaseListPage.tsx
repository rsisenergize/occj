import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { CaseOut } from "../types";
import { StatusBadge, timeAgo } from "../components/Badges";
import { useAuth } from "../auth/AuthContext";

export function CaseListPage() {
  const [cases, setCases] = useState<CaseOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);
  const navigate = useNavigate();
  const { user } = useAuth();

  async function load() {
    try {
      const data = await api.get<CaseOut[]>("/cases");
      setCases(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load cases");
    }
  }

  useEffect(() => {
    load();
    // Poll for updates -- a stand-in for Supabase Realtime, which the
    // frontend would subscribe to directly once a Supabase project is
    // provisioned (see README). Same UI, different transport.
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, []);

  async function seedDemoData() {
    setSeeding(true);
    try {
      await api.post("/demo/seed");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Seed failed");
    } finally {
      setSeeding(false);
    }
  }

  return (
    <div className="page">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h1 style={{ fontSize: 18, margin: 0 }}>Cases</h1>
        {user?.role === "admin" && (
          <button onClick={seedDemoData} disabled={seeding}>
            {seeding ? "Seeding..." : "Seed demo data"}
          </button>
        )}
      </div>
      {error && <div className="card error">{error}</div>}
      <div className="card" style={{ padding: 0 }}>
        {cases === null ? (
          <div className="empty-state" style={{ padding: 16 }}>
            Loading...
          </div>
        ) : cases.length === 0 ? (
          <div className="empty-state" style={{ padding: 16 }}>
            No cases yet. {user?.role === "admin" ? "Seed demo data to get started." : "Ask an admin to seed demo data."}
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Case</th>
                <th>Order</th>
                <th>Trigger</th>
                <th>Status</th>
                <th>Stage</th>
                <th>Last activity</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => navigate(`/cases/${c.id}`)}>
                  <td className="mono">{c.id.slice(0, 8)}</td>
                  <td>{c.order_id || "-"}</td>
                  <td>{c.trigger_type.replace(/_/g, " ")}</td>
                  <td>
                    <StatusBadge status={c.status} />
                    {c.needs_reevaluation && (
                      <span className="badge flag-contradictory" style={{ marginLeft: 6 }}>
                        re-evaluating
                      </span>
                    )}
                  </td>
                  <td className="small muted">{c.stage.replace(/_/g, " ")}</td>
                  <td className="small muted">{timeAgo(c.last_activity_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
