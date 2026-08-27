"use client";
import type { ReactNode } from "react";

function plain(status: string) {
  switch (status) {
    case "SUCCESS": return "completed successfully";
    case "FAILED": return "failed and NEXORA adapted";
    case "SKIPPED": return "was skipped (not needed or blocked)";
    case "WAITING_APPROVAL": return "is waiting for your approval";
    case "RUNNING": return "is running right now";
    default: return "hasn't started yet";
  }
}

export default function WhyModal({ node, mission, onClose }: {
  node: any; mission: any; onClose: () => void;
}) {
  const receipt = mission.receipts?.find((r: any) => r.node_id === node.node_id);
  const evidence = mission.evidence?.filter((e: any) => e.derivation_path.includes(node.node_id));
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="w-full max-w-xl rounded-lg border border-zinc-700 bg-zinc-900 p-6"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-lg font-bold text-emerald-400">{node.capability_id}</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-200">✕</button>
        </div>
        <p className="mb-3 text-sm text-zinc-200">
          This step <b>{plain(node.status)}</b>.
        </p>
        <Section t="Why NEXORA did this">
          <p className="text-sm text-zinc-300">{node.rationale_summary || "Part of the compiled plan."}</p>
        </Section>
        <Section t="Permission">
          <p className="text-sm">
            <span className={receipt?.policy_decision === "ALLOW" ? "text-emerald-400" : "text-amber-400"}>
              {receipt?.policy_decision === "ALLOW" ? "Allowed automatically (low risk)."
                : receipt?.policy_decision === "REQUIRE_APPROVAL" ? "Needed your approval (high risk)."
                : receipt?.policy_decision ?? "—"}
            </span>
          </p>
        </Section>
        {node.firewall_summary && (
          <Section t="Security">
            <p className="text-sm text-amber-300">🛡 {node.firewall_summary}</p>
          </Section>
        )}
        {evidence?.length > 0 && (
          <Section t="What it produced">
            {evidence.map((e: any) => <p key={e.evidence_id} className="text-sm text-zinc-300">“{e.claim}”</p>)}
          </Section>
        )}
      </div>
    </div>
  );
}

function Section({ t, children }: { t: string; children: ReactNode }) {
  return (
    <div className="mb-3">
      <h3 className="mb-1 text-xs font-bold tracking-widest text-zinc-500">{t.toUpperCase()}</h3>
      {children}
    </div>
  );
}