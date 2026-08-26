"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

const API = "http://localhost:8000";

export default function Home() {
  const [goal, setGoal] = useState(
    "Investigate the incident: search emails and drive files, create a tracker sheet, schedule a sync meeting, then write the incident report."
  );
  const [mission, setMission] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!mission || mission.state === "COMPLETED" || mission.state === "FAILED") return;
    const t = setInterval(async () => {
      const r = await fetch(`${API}/api/v1/missions/${mission.mission_id}`);
      if (r.ok) setMission(await r.json());
    }, 1000);
    return () => clearInterval(t);
  }, [mission]);

  useEffect(() => {
    if (!mission || (mission.state !== "COMPLETED" && mission.state !== "FAILED")) return;
    fetch(`${API}/api/v1/missions/${mission.mission_id}/events`)
      .then((r) => (r.ok ? r.json() : []))
      .then(setEvents);
  }, [mission?.state]);

  const launch = async () => {
    setLoading(true); setError(null); setMission(null); setEvents([]);
    try {
      const r = await fetch(`${API}/api/v1/missions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal, execution_mode: "MOCK" }),
      });
      if (!r.ok) throw new Error(`API error ${r.status}`);
      setMission(await r.json());
    } catch (e) { setError(String(e)); } finally { setLoading(false); }
  };

  const decide = async (nodeId: string, approved: boolean) => {
    await fetch(`${API}/api/v1/missions/${mission.mission_id}/approvals/${nodeId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    });
    const r = await fetch(`${API}/api/v1/missions/${mission.mission_id}`);
    if (r.ok) setMission(await r.json());
  };

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 p-8 font-mono">
      <header className="mb-6">
        <h1 className="text-2xl font-bold tracking-widest text-emerald-400">NEXORA</h1>
        <p className="text-sm text-zinc-400">Autonomous execution layer for the Google ecosystem</p>
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

          <Panel title="PLAN (DAG) — parallel execution">
            {mission.nodes.map((n: any) => (
              <div key={n.node_id} className="mb-2 text-xs">
                <span className="text-emerald-400">{n.capability_id}</span>{" "}
                <span className={n.status === "SUCCESS" ? "text-zinc-400" : n.status === "WAITING_APPROVAL" ? "text-amber-400" : "text-sky-400"}>
                  [{n.status}]
                </span>
                {n.depends_on?.length > 0 && <span className="text-zinc-600"> after: {n.depends_on.length} dep(s)</span>}
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

          <Panel title="HEALTH & VERIFICATION">
            <KV k="Completion" v={`${mission.health?.completion_percentage ?? 0}%`} />
            <KV k="Evidence" v={String(mission.health?.evidence_coverage ?? 0)} />
            <KV k="Verified" v={mission.verification?.overall_status ?? "—"} highlight />
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

          <Panel title="EVENT BUS">
            {events.slice(-8).map((e, i) => (
              <p key={i} className="mb-1 text-xs text-zinc-400">{e.event_type}</p>
            ))}
          </Panel>
        </div>
      )}
    </main>
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
      <span className={highlight ? "text-emerald-400" : "text-zinc-200"}>{v}</span>
    </p>
  );
}
