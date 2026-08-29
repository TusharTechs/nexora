"use client";
import { useMemo } from "react";

type Phase =
  | "UNDERSTANDING"
  | "DISCOVERING"
  | "PLANNING"
  | "EXECUTING"
  | "VERIFYING"
  | "COMPLETE"
  | "FAILED";

const PHASE_LABELS: Record<Phase, string> = {
  UNDERSTANDING: "Understanding what success looks like...",
  DISCOVERING: "Searching your workspace...",
  PLANNING: "Building the workforce and plan...",
  EXECUTING: "Executing the plan...",
  VERIFYING: "Verifying deliverables...",
  COMPLETE: "Mission Complete",
  FAILED: "Mission Failed",
};

function derivePhase(mission: any): Phase {
  if (!mission) return "UNDERSTANDING";
  if (mission.state === "COMPLETED" || mission.state === "PARTIAL_SUCCESS") return "COMPLETE";
  if (mission.state === "FAILED") return "FAILED";
  if (mission.state === "VERIFYING") return "VERIFYING";
  if (mission.state === "PLANNING" || mission.state === "CRITICIZING") return "PLANNING";
  if (mission.state === "EXECUTING" || mission.state === "BLOCKED" || mission.state === "REPLANNING") {
    if (!mission.nodes || mission.nodes.length === 0) return "PLANNING";
    return "EXECUTING";
  }
  if (mission.state === "INTERPRETING") {
    if (!mission.outcome_contract) return "UNDERSTANDING";
    if (!mission.context_bundle) return "DISCOVERING";
    return "PLANNING";
  }
  return "EXECUTING";
}

type PersonaStatus = "done" | "working" | "waiting" | "failed" | "pending";

function personaStatus(nodes: any[]): PersonaStatus {
  if (nodes.some((n) => n.status === "RUNNING")) return "working";
  if (nodes.some((n) => n.status === "FAILED" && !n.replaced_by)) return "failed";
  if (nodes.every((n) => n.status === "SUCCESS" || n.status === "SKIPPED")) return "done";
  if (nodes.some((n) => n.status === "WAITING_APPROVAL")) return "waiting";
  return "pending";
}

const STATUS_ICON: Record<PersonaStatus, string> = {
  done: "✓",
  working: "●",
  waiting: "⏸",
  failed: "✗",
  pending: "○",
};

const STATUS_COLOR: Record<PersonaStatus, string> = {
  done: "text-emerald-400",
  working: "text-sky-400 animate-pulse",
  waiting: "text-amber-400",
  failed: "text-red-400",
  pending: "text-zinc-500",
};

interface Props {
  mission: any;
  events: any[];
  onShowDetails: () => void;
}

export default function CommandCenter({ mission, events, onShowDetails }: Props) {
  const phase = derivePhase(mission);

  // Pin the type so Object.entries returns [string, any[]] instead of unknown
  const personaGroups = useMemo<Record<string, any[]>>(() => {
    if (!mission?.nodes) return {};
    return mission.nodes.reduce((acc: Record<string, any[]>, node: any) => {
      const p = node.persona || "Generalist";
      if (!acc[p]) acc[p] = [];
      acc[p].push(node);
      return acc;
    }, {} as Record<string, any[]>);
  }, [mission?.nodes]);

  const currentActivity = useMemo(() => {
    if (!mission?.nodes) return "";
    const running = mission.nodes.filter((n: any) => n.status === "RUNNING");
    if (running.length > 0) {
      return running[0].rationale_summary || `${running[0].capability_id} running...`;
    }
    const waiting = mission.nodes.filter((n: any) => n.status === "WAITING_APPROVAL");
    if (waiting.length > 0) {
      return `Awaiting your approval for ${waiting[0].capability_id}`;
    }
    return "";
  }, [mission?.nodes]);

  const totalNodes = mission?.nodes?.length || 0;
  const doneNodes =
    mission?.nodes?.filter((n: any) => n.status === "SUCCESS" || n.status === "SKIPPED")
      .length || 0;
  const progress = totalNodes > 0 ? Math.round((doneNodes / totalNodes) * 100) : 0;

  if (!mission) {
    const workforce = [
      ["Research Analyst", "gathers cited evidence"],
      ["Writer", "drafts the documents"],
      ["Financial Analyst", "builds the budgets"],
      ["Designer", "makes the deck"],
      ["Coordinator", "schedules & notifies"],
      ["Visual Designer", "generates imagery"],
    ];
    return (
      <div className="space-y-5 rounded-lg border border-zinc-800 bg-gradient-to-b from-zinc-900/60 to-zinc-950/60 p-8">
        <div className="text-center">
          <p className="text-sm text-zinc-400">Type a goal above and hit Launch.</p>
          <p className="mt-1 text-xs text-zinc-600">
            A Mission Architect writes an Outcome Contract, then this workforce delivers it — and a
            QA Auditor verifies every piece.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
          {workforce.map(([role, does]) => (
            <div key={role} className="rounded border border-zinc-800 bg-zinc-900/50 p-3">
              <p className="text-sm font-bold text-zinc-300">{role}</p>
              <p className="text-[11px] text-zinc-500">{does}</p>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (phase === "COMPLETE") {
    const verification = mission.semantic_verification;
    const deliverablesSatisfied =
      verification?.deliverables?.filter((d: any) => d.status === "SATISFIED").length || 0;
    const deliverablesTotal = verification?.deliverables?.length || 0;

    return (
      <div className="space-y-6 rounded-lg border border-emerald-800 bg-gradient-to-b from-emerald-950/60 to-zinc-900/60 p-8">
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-emerald-500/20">
            <span className="text-4xl text-emerald-400">✓</span>
          </div>
          <h2 className="text-2xl font-black text-emerald-300">Mission Complete</h2>
          <p className="mt-2 text-sm text-zinc-400">{mission.intent?.objective || mission.goal}</p>
        </div>

        {deliverablesTotal > 0 && (
          <div className="rounded border border-emerald-800 bg-emerald-900/20 p-4">
            <p className="mb-2 text-xs font-bold tracking-widest text-emerald-400">OUTCOME VERIFIED</p>
            <p className="text-sm text-zinc-200">
              {deliverablesSatisfied} of {deliverablesTotal} deliverables satisfied
              {verification?.evidence_status && ` · Evidence: ${verification.evidence_status}`}
            </p>
            {mission.replan_count > 0 && (
              <p className="mt-1 text-xs text-zinc-500">
                Required {mission.replan_count} replan cycle(s) to close gaps.
              </p>
            )}
          </div>
        )}

        {mission.workspace_uri && (
          <div className="text-center">
            <a
              href={mission.workspace_uri}
              target="_blank"
              rel="noreferrer"
              className="inline-block rounded-lg bg-emerald-500 px-8 py-4 text-lg font-black text-zinc-950 shadow-lg transition-transform hover:scale-105 hover:bg-emerald-400"
            >
              📁 Open Mission Workspace
            </a>
            <p className="mt-3 text-xs text-zinc-500">All deliverables are in one folder.</p>
          </div>
        )}

        <div className="border-t border-zinc-800 pt-4 text-center">
          <button onClick={onShowDetails} className="text-xs text-zinc-500 underline hover:text-zinc-300">
            Show technical details (DAG, events, audit trail, evidence)
          </button>
        </div>
      </div>
    );
  }

  if (phase === "FAILED") {
    return (
      <div className="space-y-4 rounded-lg border border-red-800 bg-gradient-to-b from-red-950/60 to-zinc-900/60 p-8 text-center">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-red-500/20">
          <span className="text-4xl text-red-400">✗</span>
        </div>
        <h2 className="text-2xl font-black text-red-300">Mission Failed</h2>
        <p className="text-sm text-zinc-400">
          {mission.failure_reason || "The mission could not be completed."}
        </p>
        <button onClick={onShowDetails} className="text-xs text-zinc-500 underline hover:text-zinc-300">
          Show technical details
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6 rounded-lg border border-zinc-800 bg-gradient-to-b from-zinc-900/60 to-zinc-950/60 p-8">
      <div className="text-center">
        <p className="mb-2 text-xs font-bold tracking-widest text-zinc-500">CURRENT PHASE</p>
        <h2 className="bg-gradient-to-r from-emerald-400 to-sky-400 bg-clip-text text-2xl font-black text-transparent">
          {PHASE_LABELS[phase]}
        </h2>
      </div>

      {/* Progress bar */}
      {totalNodes > 0 && phase === "EXECUTING" && (
        <div>
          <div className="mb-2 flex items-center justify-between text-xs text-zinc-500">
            <span>Progress</span>
            <span>
              {doneNodes}/{totalNodes} tasks · {progress}%
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
            <div
              className="h-full bg-gradient-to-r from-emerald-500 to-sky-500 transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Current activity */}
      {currentActivity && (
        <p className="text-center text-sm text-zinc-300">
          <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-sky-400" />
          {currentActivity}
        </p>
      )}

      {/* Workforce cards */}
      {Object.keys(personaGroups).length > 0 && (
        <div>
          <p className="mb-3 text-xs font-bold tracking-widest text-zinc-500">
            WORKFORCE · {Object.keys(personaGroups).length} SPECIALISTS
          </p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            {Object.entries(personaGroups).map(([persona, nodes]) => {
              const status = personaStatus(nodes);
              const doneCount = nodes.filter(
                (n: any) => n.status === "SUCCESS" || n.status === "SKIPPED"
              ).length;
              return (
                <div key={persona} className="rounded border border-zinc-800 bg-zinc-900/60 p-3">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-sm font-bold text-zinc-200">{persona}</span>
                    <span className={`text-lg ${STATUS_COLOR[status]}`}>{STATUS_ICON[status]}</span>
                  </div>
                  <p className="text-xs text-zinc-500">
                    {doneCount}/{nodes.length} tasks
                  </p>
                  {status === "working" && (
                    <p className="mt-1 truncate text-[10px] text-sky-400">
                      {nodes.find((n: any) => n.status === "RUNNING")?.capability_id || ""}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Phase checklist */}
      <div className="border-t border-zinc-800 pt-4">
        <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-5">
          {(["UNDERSTANDING", "DISCOVERING", "PLANNING", "EXECUTING", "VERIFYING"] as Phase[]).map(
            (p, i, arr) => {
              const currentIdx = arr.indexOf(phase);
              const thisIdx = i;
              const isDone = thisIdx < currentIdx;
              const isCurrent = thisIdx === currentIdx;
              return (
                <div
                  key={p}
                  className={`rounded px-2 py-1 text-center ${
                    isDone
                      ? "bg-emerald-900/30 text-emerald-300"
                      : isCurrent
                      ? "bg-sky-900/30 text-sky-300"
                      : "bg-zinc-900/40 text-zinc-600"
                  }`}
                >
                  {isDone ? "✓ " : isCurrent ? "● " : "○ "}
                  {p.charAt(0) + p.slice(1).toLowerCase()}
                </div>
              );
            }
          )}
        </div>
      </div>

      <div className="text-center">
        <button onClick={onShowDetails} className="text-xs text-zinc-500 underline hover:text-zinc-300">
          Show technical details
        </button>
      </div>
    </div>
  );
}