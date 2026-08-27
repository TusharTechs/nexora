"use client";
import { useState } from "react";
import DAGView from "@/components/DAGView";
import TimeTravel from "@/components/TimeTravel";
import EvidenceView from "@/components/EvidenceView";

type Tab = "dag" | "timeline" | "evidence" | "security" | "learning";

interface Props {
  mission: any;
  events: any[];
  auditTrail: any[];
  memoryList: any[];
  workflows: any[];
  teach: string;
  setTeach: (v: string) => void;
  sendTeach: () => void;
  forgeNow: () => void;
  replayNow: () => void;
  setSelectedNode: (n: any) => void;
}

export default function TechnicalDetails(props: Props) {
  const [tab, setTab] = useState<Tab>("dag");
  const [expanded, setExpanded] = useState(false);

  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="mt-6 w-full rounded border border-zinc-800 bg-zinc-900/40 py-3 text-sm text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
      >
        ▸ Technical details (DAG, events, audit, evidence, learning)
      </button>
    );
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: "dag", label: "Workflow" },
    { id: "timeline", label: "Timeline" },
    { id: "evidence", label: "Evidence" },
    { id: "security", label: "Security" },
    { id: "learning", label: "Learning" },
  ];

  const h = props.mission?.health;
  const budget = (h?.budget_consumed_usd ?? 0) + (h?.budget_remaining_usd ?? 0);
  const TERMINAL = ["COMPLETED", "FAILED", "PARTIAL_SUCCESS"];

  return (
    <div className="mt-6 space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-zinc-400">Technical Details</h3>
        <button
          onClick={() => setExpanded(false)}
          className="text-xs text-zinc-500 hover:text-zinc-300"
        >
          ▾ Collapse
        </button>
      </div>

      <nav className="flex gap-1 border-b border-zinc-800">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm ${
              tab === t.id
                ? "border-b-2 border-emerald-400 font-bold text-emerald-300"
                : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "dag" && (
        <DAGView nodes={props.mission.nodes} onSelect={props.setSelectedNode} />
      )}

      {tab === "timeline" && (
        <TimeTravel events={props.events} nodes={props.mission.nodes} />
      )}

      {tab === "evidence" && (
        <EvidenceView
          evidence={props.mission.evidence}
          artifacts={props.mission.artifacts}
        />
      )}

      {tab === "security" && (
        <div className="space-y-1">
          {props.auditTrail.length === 0 && (
            <p className="text-sm text-zinc-500">No audit events recorded.</p>
          )}
          {props.auditTrail.map((a) => (
            <p
              key={a.entry_id}
              className={`text-xs ${
                a.severity === "ALERT"
                  ? "text-red-400"
                  : a.severity === "WARN"
                  ? "text-amber-300"
                  : "text-zinc-400"
              }`}
            >
              <span className="font-bold">[{a.kind}]</span> {a.title} — {a.detail}
            </p>
          ))}
        </div>
      )}

      {tab === "learning" && (
        <div className="space-y-4">
          <div className="flex gap-2">
            <input
              value={props.teach}
              onChange={(e) => props.setTeach(e.target.value)}
              placeholder='Teach NEXORA a rule — e.g. "Always require my approval before scheduling meetings."'
              className="flex-1 rounded border border-sky-800 bg-zinc-900 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none"
            />
            <button
              onClick={props.sendTeach}
              className="rounded bg-sky-600 px-4 py-2 text-sm font-bold hover:bg-sky-500"
            >
              Teach
            </button>
          </div>
          <section className="rounded border border-zinc-800 bg-zinc-900/60 p-4">
            <h2 className="mb-3 text-xs font-bold tracking-widest text-zinc-400">
              MEMORY & FORGED WORKFLOWS
            </h2>
            {props.memoryList.length === 0 && props.workflows.length === 0 && (
              <p className="text-xs text-zinc-500">No memories or workflows yet.</p>
            )}
            {props.memoryList.slice(-6).map((m: any) => (
              <p key={m.memory_id} className="mb-1 text-xs text-zinc-400">
                <span className="text-sky-400">[{m.type}/{m.scope}]</span> {m.content}
                {m.effect ? ` → ${m.effect}` : ""}
              </p>
            ))}
            {props.workflows.slice(-3).map((w: any) => (
              <p key={w.template_id} className="mb-1 text-xs text-amber-300">
                ⚒ {w.name} · ${w.expected_cost_usd}
              </p>
            ))}
          </section>
        </div>
      )}

      {TERMINAL.includes(props.mission.state) && (
        <div className="flex gap-2 border-t border-zinc-800 pt-4">
          <button
            onClick={props.forgeNow}
            className="rounded bg-amber-600 px-4 py-2 text-sm font-bold hover:bg-amber-500"
          >
            ⚒ Forge workflow
          </button>
          <button
            onClick={props.replayNow}
            className="rounded bg-zinc-700 px-4 py-2 text-sm font-bold hover:bg-zinc-600"
          >
            ↺ Replay
          </button>
        </div>
      )}
    </div>
  );
}