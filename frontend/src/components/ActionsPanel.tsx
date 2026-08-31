import { useState } from "react";
import type { ActionRequestOut, ApprovalOut } from "../types";
import { StatusBadge, formatMoney } from "./Badges";
import { useAuth } from "../auth/AuthContext";
import { api } from "../api/client";

interface Props {
  actions: ActionRequestOut[];
  approvals: ApprovalOut[];
  onChanged: () => void;
}

export function ActionsPanel({ actions, approvals, onChanged }: Props) {
  const { user } = useAuth();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});

  async function decide(approvalId: string, decision: "approved" | "rejected") {
    setBusyId(approvalId);
    try {
      await api.post(`/approvals/${approvalId}/decide`, { decision, note: notes[approvalId] || null });
      onChanged();
    } finally {
      setBusyId(null);
    }
  }

  const approvalByAction = new Map(approvals.map((a) => [a.action_request_id, a]));

  return (
    <div className="card">
      <h2>Actions</h2>
      {actions.length === 0 ? (
        <div className="empty-state">No actions taken yet.</div>
      ) : (
        [...actions].reverse().map((a) => {
          const approval = approvalByAction.get(a.id);
          const canDecide =
            approval &&
            approval.status === "pending" &&
            user &&
            (user.role === "admin" || user.role === approval.required_role);
          return (
            <div className="action-card" key={a.id}>
              <div className="row">
                <strong>{a.action_type.replace(/_/g, " ")}</strong>
                <StatusBadge status={a.status} />
              </div>
              <div className="rationale">{a.rationale}</div>
              {typeof a.target?.estimated_cost_usd === "number" && (
                <div className="small muted">Estimated cost: {formatMoney(a.target.estimated_cost_usd)}</div>
              )}
              {typeof a.target?.message === "string" && (
                <div className="small" style={{ background: "var(--accent-soft)", padding: 8, borderRadius: 6 }}>
                  &ldquo;{a.target.message}&rdquo;
                </div>
              )}
              {approval && (
                <div className="small muted">
                  Approval required: {approval.required_role} &middot; status: {approval.status}
                  {approval.decision_note && <> &middot; note: {approval.decision_note}</>}
                </div>
              )}
              {canDecide && (
                <div className="approve-row">
                  <textarea
                    placeholder="Optional note"
                    value={notes[approval!.id] || ""}
                    onChange={(e) => setNotes({ ...notes, [approval!.id]: e.target.value })}
                  />
                  <button
                    className="primary"
                    disabled={busyId === approval!.id}
                    onClick={() => decide(approval!.id, "approved")}
                  >
                    Approve
                  </button>
                  <button
                    className="danger"
                    disabled={busyId === approval!.id}
                    onClick={() => decide(approval!.id, "rejected")}
                  >
                    Reject
                  </button>
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
