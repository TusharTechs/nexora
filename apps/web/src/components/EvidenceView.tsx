"use client";
import { useState } from "react";

export default function EvidenceView({ evidence, artifacts }: { evidence: any[]; artifacts: any[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!evidence?.length) return <p className="text-sm text-zinc-500">No evidence yet.</p>;
  return (
    <div className="space-y-2">
      {evidence.map((e) => (
        <div key={e.evidence_id} className="rounded border border-zinc-800 bg-zinc-900/60 p-3">
          <button className="text-left text-sm text-zinc-100"
            onClick={() => setOpen(open === e.evidence_id ? null : e.evidence_id)}>
            <span className="mr-2 text-emerald-400">◆</span>“{e.claim}”
            <span className="ml-2 text-[10px] text-zinc-500">confidence {e.confidence}</span>
          </button>
          {open === e.evidence_id && (
            <div className="ml-5 mt-2 space-y-1 border-l border-zinc-700 pl-3">
              {e.sources.map((sid: string) => {
                const art = artifacts.find((a) => a.artifact_id === sid);
                return (
                  <p key={sid} className="text-xs text-zinc-400">
                    ↳ source: {art ? `${art.type} · ${art.uri}` : sid}
                  </p>
                );
              })}
              <p className="text-[10px] text-zinc-500">derived via {e.derivation_path.length} node(s)</p>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}