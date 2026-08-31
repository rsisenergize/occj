const STAGES = [
  "issue_reported",
  "journey_assembled",
  "failure_located",
  "evidence_checked",
  "impact_assessed",
  "recovery_options_ranked",
  "actions_coordinated",
  "customer_updated",
  "outcome_retained",
];

export function StageTracker({ stage }: { stage: string }) {
  const currentIndex = STAGES.indexOf(stage);
  return (
    <div className="stage-tracker">
      {STAGES.map((s, i) => (
        <span
          key={s}
          className={`stage-step ${i < currentIndex ? "done" : ""} ${i === currentIndex ? "current" : ""}`}
        >
          {i + 1}. {s.replace(/_/g, " ")}
        </span>
      ))}
    </div>
  );
}
