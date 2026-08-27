"use client";

function Gauge({ label, value, color }: { label: string; value: number; color: string }) {
  const r = 34, c = 2 * Math.PI * r;
  const frac = Math.max(0, Math.min(1, value));
  return (
    <div className="flex flex-col items-center">
      <svg width="92" height="92">
        <circle cx="46" cy="46" r={r} stroke="#27272a" strokeWidth="8" fill="none" />
        <circle cx="46" cy="46" r={r} stroke={color} strokeWidth="8" fill="none"
          strokeDasharray={`${c * frac} ${c}`} strokeLinecap="round" transform="rotate(-90 46 46)" />
        <text x="46" y="51" textAnchor="middle" fill="#e4e4e7" fontSize="15" fontFamily="monospace">
          {Math.round(frac * 100)}%
        </text>
      </svg>
      <span className="text-xs text-zinc-400">{label}</span>
    </div>
  );
}

export default function HealthGauges({ health, budget }: { health: any; budget: number }) {
  const completion = (health?.completion_percentage ?? 0) / 100;
  const evidence = health?.evidence_coverage ?? 0;
  const consumed = health?.budget_consumed_usd ?? 0;
  const budgetFrac = budget > 0 ? consumed / budget : 0;
  return (
    <div className="flex flex-wrap items-center gap-6">
      <Gauge label="Completion" value={completion} color="#34d399" />
      <Gauge label="Evidence" value={evidence} color="#38bdf8" />
      <Gauge label="Budget used" value={budgetFrac} color="#fbbf24" />
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-zinc-300">
        <span>Policy risk: <b>{health?.policy_risk_score ?? 0}</b></span>
        <span>Retries: <b>{health?.retry_count ?? 0}</b></span>
        <span>Replans: <b>{health?.replan_count ?? 0}</b></span>
        <span>Failed: <b>{(health?.failed_nodes ?? []).length}</b></span>
      </div>
    </div>
  );
}