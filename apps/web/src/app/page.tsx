"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

const API = "http://localhost:8000";

type AuditEntry = {
  entry_id: string;
  kind: string;
  severity: string;
  title: string;
  detail: string;
  metadata: any;
  timestamp: string;
  node_id?: string;
};

export default function Home() {
  const [goal, setGoal] = useState(
    "Search emails then write the incident report."
  );
  const [mission, setMission] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [auditTrail, setAuditTrail] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<any | null>(null);
  const wsOk = useRef(false);

  const refresh = async (mid: string) => {
    const r = await fetch(`${API}/api/v1/missions/${mid}`);
    if (r.ok) setMission(await r.json());
  };

  useEffect(() => {
    if (!mission) return;
    const mid = mission.mission_id;
    let poll: any = null;
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(`ws://localhost:8000/api/v1/missions/${mid}/ws`);
      ws.onmessage = () => refresh(mid);
      ws.onopen = () => { wsOk.current = true; };
      ws.onerror = () => { poll = setInterval(() => refresh(mid), 1500); };
    } catch {
      poll = setInterval(() => refresh(mid), 1500);
    }
    return () => { ws?.close(); if (poll) clearInterval(poll); };
  }, [mission?.mission_id]);

  useEffect(() => {
    if (!mission) return;
    const terminal = ["COMPLETED", "FAILED", "PARTIAL_SUCCESS"].includes(mission.state);
    if (terminal) {
      fetch(`${API}/api/v1/missions/${mission.mission_id}/events`).then(r => r.ok ? r.json() : []).then(setEvents);
      fetch(`${API}/api/v1/missions/${mission.mission_id}/audit`).then(r => r.ok ? r.json() : []).then(setAuditTrail);
    }
  }, [mission?.state]);

  const launch = async () => {
    setLoading(true); setError(null); setMission(null); setEvents([]); setAuditTrail([]);
    try {
      const r = await fetch(`${API}/api/v1/missions`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal, execution_mode: "MOCK" }),
      });
      if (!r.ok) throw new Error(`API error ${r.status}`);
      setMission(await r.json());
    } catch (e) { setError(String(e)); } finally { setLoading(false); }
  };

  const decide = async (nodeId: string, approved: boolean) => {
    await fetch(`${API}/api/v1/missions/${mission.mission_id}/approvals/${nodeId}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    });
    refresh(mission.mission_id);
  };

  const h = mission?.health;
  const firewallAlerts = auditTrail.filter(a => a.kind === "FIREWALL_DETECT").length;
  const policyBlocks = auditTrail.filter(a =>
    a.kind === "POLICY_DECISION" && a.metadata?.decision === "BLOCK").length;

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 p-8 font-mono">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-widest text-emerald-400">NEXORA</h1>
          <p className="text-sm text-zinc-400">Autonomous execution layer for the Google ecosystem</p>
        </div>
        <a href="/explorer" className="text-xs text-zinc-400 underline">Capability Explorer →</a>
      </header>

      <section className="mb-6 flex gap-2">
        <input value={goal} onChange={(e) => setGoal(e.target.value)}
          className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm" />
        <button onClick={launch} disabled={loading}
          className="rounded bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 disabled:opacity-50">
          {loading ? "Launching…" : "Launch Mission"}
        </button>
      </section>

      {error && <p className="mb-4 text-red-400">Error: {error}</p>}

      {mission && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <Panel title="MISSION">
            <KV k="State" v={mission.state} highlight />
            <KV k="Mode" v={mission.execution_mode} />
            <KV k="Objective" v={mission.intent?.objective ?? "—"} />
          </Panel>

          <Panel title="PLAN (DAG) — click a node for WHY">
            {mission.nodes.map((n: any) => (
              <div key={n.node_id} className="mb-2 text-xs cursor-pointer hover:bg-zinc-800/50 rounded p-1"
                   onClick={() => setSelectedNode(n)}>
                <span className="text-emerald-400">{n.capability_id}</span>{" "}
                <span className={
                  n.status === "SUCCESS" ? "text-zinc-400"
                  : n.status === "WAITING_APPROVAL" ? "text-amber-400"
                  : n.status === "SKIPPED" ? "text-zinc-600 line-through"
                  : n.status === "FAILED" ? "text-red-400" : "text-sky-400"}>
                  [{n.status}{n.retries ? ` retry×${n.retries}` : ""}]
                </span>
                {n.condition && <span className="text-violet-400">  conditional</span>}
                {n.firewall_summary && (
                  <span className="ml-2 text-amber-300">🛡 {n.firewall_summary}</span>
                )}
              </div>
            ))}
            {mission.nodes.filter((n: any) => n.status === "WAITING_APPROVAL").map((n: any) => (
              <div key={`ap-${n.node_id}`} className="mt-2 flex items-center gap-2 text-xs">
                <span className="text-amber-400">{n.capability_id} requires approval</span>
                <button onClick={() => decide(n.node_id, true)} className="rounded bg-emerald-600 px-2 py-1">Approve</button>
                <button onClick={() => decide(n.node_id, false)} className="rounded bg-red-700 px-2 py-1">Reject</button>
              </div>
            ))}
          </Panel>

          <Panel title="MISSION HEALTH (9 metrics)">
            <KV k="Completion" v={`${h?.completion_percentage ?? 0}%`} />
            <KV k="Evidence coverage" v={`${h?.evidence_coverage ?? 0} (${mission.evidence?.length ?? 0} claims)`} />
            <KV k="Policy risk" v={String(h?.policy_risk_score ?? 0)} />
            <KV k="Budget" v={`$${h?.budget_consumed_usd ?? 0} / $${((h?.budget_consumed_usd ?? 0) + (h?.budget_remaining_usd ?? 0)).toFixed(4)}`} />
            <KV k="Remaining" v={`$${h?.budget_remaining_usd ?? 0}`} />
            <KV k="Blocked" v={(h?.blocked_objectives ?? []).join(", ") || "none"} />
            <KV k="Failed nodes" v={String((h?.failed_nodes ?? []).length)} />
            <KV k="Retries" v={String(h?.retry_count ?? 0)} />
            <KV k="Replans" v={String(h?.replan_count ?? 0)} />
          </Panel>

          <Panel title="🛡 SECURITY CENTER">
            <KV k="Firewall detections" v={String(firewallAlerts)} highlight={firewallAlerts > 0} />
            <KV k="Policy blocks" v={String(policyBlocks)} highlight={policyBlocks > 0} />
            <KV k="Audit events" v={String(auditTrail.length)} />
            <div className="mt-2 space-y-1 max-h-48 overflow-y-auto">
              {auditTrail.slice(0, 8).map((a) => (
                <p key={a.entry_id} className={`text-xs ${
                  a.severity === "ALERT" ? "text-red-400" :
                  a.severity === "WARN"  ? "text-amber-300" : "text-zinc-400"
                }`}>
                  [{a.kind}] {a.title} — {a.detail}
                </p>
              ))}
            </div>
          </Panel>

          <Panel title="ARTIFACTS">
            {mission.artifacts.map((a: any) => (
              <p key={a.artifact_id} className="mb-1 text-xs text-zinc-300">
                {a.type} · {a.provider} · <span className="text-zinc-500">{a.uri}</span>
              </p>
            ))}
          </Panel>

          <Panel title="ACTION RECEIPTS">
            {mission.receipts.map((r: any) => (
              <p key={r.receipt_id} className="mb-1 text-xs text-zinc-300">
                {r.capability_id} · {r.policy_decision} · {r.cost_usd} USD
              </p>
            ))}
          </Panel>
        </div>
      )}

      {selectedNode && (
        <WhyModal node={selectedNode} mission={mission}
                  audit={auditTrail.filter(a => a.node_id === selectedNode.node_id)}
                  onClose={() => setSelectedNode(null)} />
      )}
    </main>
  );
}

function WhyModal({ node, mission, audit, onClose }: {
  node: any; mission: any; audit: AuditEntry[]; onClose: () => void;
}) {
  const receipt = mission.receipts.find((r: any) => r.node_id === node.node_id);
  const evidence = mission.evidence.filter((e: any) =>
    e.derivation_path.includes(node.node_id));
  const fw = node.outputs?.search_results_firewall || node.outputs?.email_firewall;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
         onClick={onClose}>
      <div className="w-full max-w-2xl rounded-lg border border-zinc-700 bg-zinc-900 p-6"
           onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-lg font-bold text-emerald-400">Why: {node.capability_id}</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-200">✕</button>
        </div>

        <Section title="Rationale">
          <p className="text-sm text-zinc-200">{node.rationale_summary || "—"}</p>
        </Section>

        <Section title="Policy decision">
          <p className="text-sm">
            <span className={receipt?.policy_decision === "ALLOW" ? "text-emerald-400" : "text-amber-400"}>
              {receipt?.policy_decision ?? "—"}
            </span>
            {node.firewall_summary && <span className="ml-2 text-amber-300">🛡 {node.firewall_summary}</span>}
          </p>
        </Section>

        {fw && (
          <Section title="Content Firewall">
            <p className="text-sm text-zinc-200">Verdict: <b>{fw.verdict}</b></p>
            {fw.per_message && fw.per_message.map((m: any, i: number) => (
              <p key={i} className="mt-1 text-xs text-zinc-400">
                {m.id}: {m.verdict}
                {m.matches?.length > 0 && <span className="text-red-400"> — {m.matches.map((x:any)=>x.category).join(", ")}</span>}
              </p>
            ))}
          </Section>
        )}

        <Section title="Evidence">
          {evidence.length === 0 && <p className="text-sm text-zinc-500">—</p>}
          {evidence.map((e: any) => (
            <p key={e.evidence_id} className="mb-1 text-sm text-zinc-300">“{e.claim}” ({e.confidence})</p>
          ))}
        </Section>

        <Section title="Audit events for this node">
          {audit.length === 0 && <p className="text-sm text-zinc-500">—</p>}
          {audit.map((a) => (
            <p key={a.entry_id} className="mb-1 text-xs text-zinc-400">
              [{a.kind}] {a.title} — {a.detail}
            </p>
          ))}
        </Section>

        <Section title="Action receipt">
          {receipt ? (
            <pre className="overflow-x-auto text-xs text-zinc-300">{JSON.stringify(receipt, null, 2)}</pre>
          ) : (
            <p className="text-sm text-zinc-500">Not executed yet.</p>
          )}
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mb-4">
      <h3 className="mb-1 text-xs font-bold tracking-widest text-zinc-400">{title.toUpperCase()}</h3>
      {children}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded border border-zinc-800 bg-zinc-900/60 p-4">
      <h2 className="mb-3 text-xs font-bold tracking-widest text-zinc-400">{title}</h2>
      {children}
    </section>
  );
}

function KV({ k, v, highlight }: { k: string; v: string; highlight?: boolean }) {
  return (
    <p className="mb-1 text-xs">
      <span className="text-zinc-500">{k}: </span>
      <span className={highlight ? "text-amber-300" : "text-zinc-200"}>{v}</span>
    </p>
  );
}