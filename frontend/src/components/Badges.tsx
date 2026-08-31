export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge status-${status}`}>{status.replace(/_/g, " ")}</span>;
}

export function FlagBadge({ flagType }: { flagType: string }) {
  return <span className={`badge flag-${flagType}`}>{flagType}</span>;
}

export function timeAgo(iso: string): string {
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export function formatMoney(n: number): string {
  return `$${n.toFixed(2)}`;
}
