import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ApprovalOut } from "../types";

export function ApprovalsQueuePage() {
  const [approvals, setApprovals] = useState<ApprovalOut[] | null>(null);

  async function load() {
    const data = await api.get<ApprovalOut[]>("/approvals");
    setApprovals(data);
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="page">
      <h1 style={{ fontSize: 18 }}>Pending approvals</h1>
      <div className="card" style={{ padding: 0 }}>
        {approvals === null ? (
          <div className="empty-state" style={{ padding: 16 }}>Loading...</div>
        ) : approvals.length === 0 ? (
          <div className="empty-state" style={{ padding: 16 }}>Nothing pending for your role right now.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Required role</th>
                <th>Requested</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {approvals.map((a) => (
                <tr key={a.id}>
                  <td><span className="badge role">{a.required_role}</span></td>
                  <td className="small muted">{new Date(a.created_at).toLocaleString()}</td>
                  <td>
                    <Link to={a.case_id ? `/cases/${a.case_id}` : "/cases"} className="small">
                      Open case &rarr;
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="small muted">
        Open the relevant case to see full context (hypothesis, impact, rationale) before approving or rejecting.
      </div>
    </div>
  );
}
