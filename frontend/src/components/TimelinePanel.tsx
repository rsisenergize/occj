import type { CanonicalEventOut, UncertaintyFlagOut } from "../types";
import { FlagBadge } from "./Badges";

export function TimelinePanel({ events, flags }: { events: CanonicalEventOut[]; flags: UncertaintyFlagOut[] }) {
  return (
    <div className="card">
      <h2>Journey timeline</h2>
      {flags.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          {flags
            .filter((f) => !f.resolved_at)
            .map((f) => (
              <div key={f.id} className={`uncertainty-banner ${f.flag_type}`}>
                <FlagBadge flagType={f.flag_type} />
                <span>{f.description}</span>
              </div>
            ))}
        </div>
      )}
      {events.length === 0 ? (
        <div className="empty-state">No evidence assembled yet.</div>
      ) : (
        events.map((e) => (
          <div key={e.id} className="timeline-item">
            <div className="dot" />
            <div style={{ flex: 1 }}>
              <div>{e.summary}</div>
              <div className="meta">
                {e.source_type.replace(/_/g, " ")} &middot; {new Date(e.effective_at).toLocaleString()}
              </div>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
