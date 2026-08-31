import type { ImpactAssessmentOut } from "../types";
import { formatMoney } from "./Badges";

export function ImpactPanel({ impact }: { impact: ImpactAssessmentOut | null }) {
  if (!impact) return null;
  return (
    <div className="card">
      <h2>Impact assessment</h2>
      <div className="pill-row">
        <span className="badge status-pending_approval">Exposure {formatMoney(impact.financial_exposure_usd)}</span>
        <span className="badge role">SLA breach {Math.round(impact.sla_breach_score * 100)}%</span>
        <span className="badge role">Tier weight &times;{impact.customer_tier_weight}</span>
        <span className="badge status-closed">Composite {impact.composite_score.toFixed(1)}</span>
      </div>
      <div className="small muted">composite = exposure &times; tier_weight &times; (1 + sla_breach_score)</div>
    </div>
  );
}
