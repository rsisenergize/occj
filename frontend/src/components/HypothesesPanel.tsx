import type { HypothesisOut } from "../types";

export function HypothesesPanel({ hypotheses, primaryId }: { hypotheses: HypothesisOut[]; primaryId: string | null }) {
  const sorted = [...hypotheses].sort((a, b) => b.confidence - a.confidence);
  return (
    <div className="card">
      <h2>Competing hypotheses</h2>
      {sorted.length === 0 ? (
        <div className="empty-state">No evidence-grounded hypothesis yet.</div>
      ) : (
        sorted.map((h) => (
          <div key={h.id} className={`hypothesis-card ${h.status === "superseded" ? "superseded" : ""}`}>
            <div className="title-row">
              <strong>
                {h.title} {h.id === primaryId && <span className="badge status-closed">leading</span>}
              </strong>
              <span className="small muted">{Math.round(h.confidence * 100)}% confidence</span>
            </div>
            <div className="confidence-bar">
              <div className="confidence-bar-fill" style={{ width: `${Math.round(h.confidence * 100)}%` }} />
            </div>
            <div className="narrative">{h.narrative}</div>
            <div className="links">
              {h.evidence_links.filter((l) => l.relation === "supports").length} supporting &middot;{" "}
              {h.evidence_links.filter((l) => l.relation === "weakens").length} weakening &middot; status:{" "}
              {h.status}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
