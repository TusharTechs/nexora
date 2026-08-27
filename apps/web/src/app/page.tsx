"use client";
import { useEffect, useRef, useState } from "react";
import DAGView from "@/components/DAGView";
import TimeTravel from "@/components/TimeTravel";
import HealthGauges from "@/components/HealthGauges";
import EvidenceView from "@/components/EvidenceView";
import WhyModal from "@/components/WhyModal";
import { useVoice } from "@/hooks/useVoice";

const API = "http://localhost:8000";
const TERMINAL = ["COMPLETED", "FAILED", "PARTIAL_SUCCESS"];
const SCENARIOS = [
  { label: "💼 Business Launch", goal: "I'm starting my new business project tomorrow. Prepare everything I need: business plan doc, learning materials, budget sheet, pitch deck, kickoff meeting, and tasks." },
  { label: "🚀 Launch Aurora", goal: "Prepare everything to launch Product X next Friday: research, budget sheet, meetings, deck, announcement." },
  { label: "🚨 Customer Escalation", goal: "A customer sent a screenshot of a production error. Investigate, analyze the screenshot, estimate impact, create the incident report, notify the team, and create follow-up tasks." },
  { label: "📊 Weekly Review", goal: "Search emails and drive files, read the metrics sheet, and write the weekly business report." },
];
type Tab = "overview" | "timeline" | "dag" | "evidence" | "security" | "learning";

// Safe fetch wrapper so the UI never crashes if the backend is down
async function safeGet(url: string): Promise<any | null> {
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

export default function Home() {
  const [goal, setGoal] = useState(SCENARIOS[1].goal);
  const [intervention, setIntervention] = useState("");
  const [teach, setTeach] = useState("");
  const [mission, setMission] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [auditTrail, setAuditTrail] = useState<any[]>([]);
  const [memoryList, setMemoryList] = useState<any[]>([]);
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<any | null>(null);
  const [gConnected, setGConnected] = useState<boolean | null>(null);

  // Phase 9.2: Attachment & Voice State
  const [attachment, setAttachment] = useState<any | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const voice = useVoice((text) => setGoal(text));

  // Phase 9.4: deep-link from Scenario Gallery (?goal=...)
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("goal");
    if (q) setGoal(q);
  }, []);

  const onFile = (e: any) => {
    const f = e.target.files?.[0];
    if (f) setAttachment({ name: f.name, type: f.type || "image/png", text: "" });
  };

  const refresh = async (mid: string) => {
    const d = await safeGet(`${API}/api/v1/missions/${mid}`);
    if (d) setMission(d);
  };

  const refreshLearning = async () => {
    const m = await safeGet(`${API}/api/v1/memory`); if (m) setMemoryList(m);
    const w = await safeGet(`${API}/api/v1/workflows`); if (w) setWorkflows(w);
  };

  useEffect(() => { refreshLearning(); }, []);

  useEffect(() => {
    if (!mission) return;
    const mid = mission.mission_id;
    let poll: any = null; let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(`ws://localhost:8000/api/v1/missions/${mid}/ws`);
      ws.onmessage = () => refresh(mid);
      ws.onerror = () => { poll = setInterval(() => refresh(mid), 1500); };
    } catch { poll = setInterval(() => refresh(mid), 1500); }
    return () => { ws?.close(); if (poll) clearInterval(poll); };
  }, [mission?.mission_id]);

  useEffect(() => {
    if (!mission || !TERMINAL.includes(mission.state)) return;
    safeGet(`${API}/api/v1/missions/${mission.mission_id}/events`).then((d) => setEvents(d ?? []));
    safeGet(`${API}/api/v1/missions/${mission.mission_id}/audit`).then((d) => setAuditTrail(d ?? []));
  }, [mission?.state]);

  useEffect(() => { safeGet(`${API}/api/v1/auth/status`).then((d) => setGConnected(d?.connected ?? false)); }, []);

  const launch = async () => {
    setLoading(true); setError(null); setMission(null);
    try {
      const r = await fetch(`${API}/api/v1/missions`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal, execution_mode: "MOCK", attachment }),
      });
      if (!r.ok) throw new Error(`API error ${r.status}`);
      setMission(await r.json()); setTab("overview");
      setAttachment(null);
      if (fileRef.current) fileRef.current.value = "";
    } catch (e) { setError(String(e)); } finally { setLoading(false); }
  };

  const decide = async (nodeId: string, approved: boolean) => {
    await fetch(`${API}/api/v1/missions/${mission.mission_id}/approvals/${nodeId}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved }) });
    refresh(mission.mission_id);
  };

  const sendIntervention = async () => {
    if (!intervention.trim() || !mission) return;
    await fetch(`${API}/api/v1/missions/${mission.mission_id}/intervene`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ instruction: intervention }) });
    setIntervention(""); refresh(mission.mission_id);
  };

  const sendTeach = async () => {
    if (!teach.trim()) return;
    await fetch(`${API}/api/v1/memory/teach`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ instruction: teach }) });
    setTeach(""); refreshLearning();
  };

  const forgeNow = async () => {
    await fetch(`${API}/api/v1/missions/${mission.mission_id}/forge`, { method: "POST" });
    refreshLearning();
  };

  const replayNow = async () => {
    const r = await fetch(`${API}/api/v1/missions/${mission.mission_id}/replay`, { method: "POST" });
    if (r.ok) setMission(await r.json());
  };

  const h = mission?.health;
  const budget = (h?.budget_consumed_usd ?? 0) + (h?.budget_remaining_usd ?? 0);
  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Overview" }, { id: "dag", label: "Workflow" },
    { id: "timeline", label: "Timeline" }, { id: "evidence", label: "Evidence" },
    { id: "security", label: "Security" }, { id: "learning", label: "Learning" },
  ];

  return (
    <main className="min-h-screen bg-zinc-950 p-6 font-mono text-zinc-100 lg:p-10">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <h1 className="bg-gradient-to-r from-emerald-400 to-sky-400 bg-clip-text text-3xl font-black tracking-widest text-transparent">NEXORA</h1>
          <p className="text-sm text-zinc-400">Give it the goal. It builds the organization.</p>
        </div>
        <div className="flex gap-4 text-xs">
          <a href="/scenarios" className="text-zinc-400 underline">Scenario Gallery →</a>
          {gConnected === false && (
            <a href={`${API}/api/v1/auth/google`} className="text-sky-400 underline">🔗 Connect Google</a>
          )}
          {gConnected === true && <span className="text-emerald-400">● Google connected</span>}
          <a href="/explorer" className="text-zinc-400 underline">Capability Explorer →</a>
        </div>
      </header>

      <section className="mb-3 flex flex-wrap items-center gap-2">
        {SCENARIOS.map((s) => (
          <button key={s.label} onClick={() => setGoal(s.goal)}
            className={`rounded-full border px-3 py-1 text-xs ${goal === s.goal ? "border-emerald-500 bg-emerald-900/40 text-emerald-200" : "border-zinc-700 text-zinc-400 hover:border-zinc-500"}`}>
            {s.label}
          </button>
        ))}
      </section>

      {/* Goal Input + Attach + Voice + Launch */}
      <section className="mb-3 flex gap-2">
        <input value={goal} onChange={(e) => setGoal(e.target.value)}
          placeholder="What should NEXORA accomplish?"
          className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none" />

        <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={onFile} />

        <button onClick={() => fileRef.current?.click()} title="Attach a screenshot/image"
          className={`rounded border px-3 py-2 text-sm ${attachment ? "border-sky-500 bg-sky-900/30 text-sky-300" : "border-zinc-700 text-zinc-400 hover:border-zinc-500"}`}>
          📎
        </button>

        <button onClick={voice.toggle} disabled={!voice.supported}
          title={voice.supported ? "Speak your goal" : "Voice not supported in this browser (use Chrome/Edge)"}
          className={`rounded border px-3 py-2 text-sm ${voice.listening ? "animate-pulse border-red-500 bg-red-900/30 text-red-400" : "border-zinc-700 text-zinc-400 hover:border-zinc-500 disabled:opacity-50"}`}>
          🎤
        </button>

        <button onClick={launch} disabled={loading}
          className="rounded bg-emerald-500 px-5 py-2 text-sm font-bold text-zinc-950 hover:bg-emerald-400 disabled:opacity-50">
          {loading ? "Launching…" : "Launch Mission"}
        </button>
      </section>

      {attachment && (
        <p className="mb-3 flex items-center gap-2 text-xs text-sky-300">
          📎 Attached: <span className="font-bold">{attachment.name}</span>
          <span className="text-zinc-500">— NEXORA will analyze it using Gemini vision.</span>
        </p>
      )}
      {voice.listening && (
        <p className="mb-3 flex items-center gap-2 text-xs text-red-400 animate-pulse">
          🎤 Listening… speak your goal, then click Launch.
        </p>
      )}

      {mission && !TERMINAL.includes(mission.state) && (
        <section className="mb-4 flex gap-2">
          <input value={intervention} onChange={(e) => setIntervention(e.target.value)}
            placeholder='Change the mission live — e.g. "Stop all external communication."'
            className="flex-1 rounded border border-violet-800 bg-zinc-900 px-3 py-2 text-sm focus:border-violet-500 focus:outline-none" />
          <button onClick={sendIntervention} className="rounded bg-violet-600 px-4 py-2 text-sm font-bold text-zinc-950 hover:bg-violet-500">Intervene</button>
        </section>
      )}

      {error && <p className="mb-4 rounded border border-red-800 bg-red-900/20 p-2 text-sm text-red-400">Error: {error}</p>}

      {mission && (
        <>
          <div className="mb-4 flex items-center gap-4 rounded border border-zinc-800 bg-zinc-900/60 px-4 py-2">
            <span className="text-sm text-zinc-400">Mission:</span>
            <span className={`text-sm font-bold ${mission.state === "COMPLETED" ? "text-emerald-400" : mission.state === "FAILED" ? "text-red-400" : "text-sky-400"}`}>
              {mission.state}
            </span>
            <span className="truncate text-xs text-zinc-500">{mission.intent?.objective}</span>
          </div>

          <nav className="mb-5 flex gap-1 border-b border-zinc-800">
            {tabs.map((t) => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={`px-4 py-2 text-sm transition-colors ${tab === t.id ? "border-b-2 border-emerald-400 font-bold text-emerald-300" : "text-zinc-500 hover:text-zinc-300"}`}>
                {t.label}
              </button>
            ))}
          </nav>

          {tab === "overview" && (
            <div className="space-y-6">
                            {mission.semantic_verification && (
                <div className={`rounded border p-3 text-sm ${
                  mission.semantic_verification.complete
                    ? "border-emerald-700 bg-emerald-900/20"
                    : "border-amber-700 bg-amber-900/20"
                }`}>
                  <p className="mb-2 text-xs font-bold tracking-widest text-zinc-400">SEMANTIC VERIFICATION</p>
                  <p className="mb-2 text-sm">
                    {mission.semantic_verification.complete ? (
                      <span className="text-emerald-400">✓ All deliverables satisfied</span>
                    ) : (
                      <span className="text-amber-400">⚠ Outcome incomplete: {mission.semantic_verification.rationale}</span>
                    )}
                  </p>
                  <ul className="ml-4 list-disc text-xs space-y-1">
                    {mission.semantic_verification.deliverables?.map((d: any, i: number) => (
                      <li key={i} className={
                        d.status === "SATISFIED" ? "text-emerald-300"
                        : d.status === "PARTIAL" ? "text-amber-300"
                        : "text-red-400"
                      }>
                        <span className="font-bold">[{d.status}]</span> {d.name}
                        {d.reason && <span className="text-zinc-400"> — {d.reason}</span>}
                      </li>
                    ))}
                  </ul>
                  {mission.semantic_verification.recommended_next_actions?.length > 0 && (
                    <div className="mt-3">
                      <p className="text-xs font-bold text-zinc-400">RECOMMENDED NEXT ACTIONS</p>
                      <ul className="ml-4 list-disc text-xs text-zinc-300">
                        {mission.semantic_verification.recommended_next_actions.map((a: string, i: number) => (
                          <li key={i}>{a}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
              <HealthGauges health={h} budget={budget} />
              {mission.outcome_contract && (
                <div className="rounded border border-sky-800 bg-sky-900/20 p-3 text-sm">
                  <p className="mb-2 text-xs font-bold tracking-widest text-sky-400">OUTCOME CONTRACT</p>
                  <p className="mb-1 text-zinc-200">{mission.outcome_contract.objective}</p>
                  {mission.outcome_contract.required_deliverables?.length > 0 && (
                    <>
                      <p className="mt-2 text-xs text-zinc-500">Deliverables:</p>
                      <ul className="ml-4 list-disc text-xs text-zinc-300">
                        {mission.outcome_contract.required_deliverables.map((d: string, i: number) => (
                          <li key={i}>{d}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  {mission.outcome_contract.needs_external_research && (
                    <p className="mt-2 text-xs text-amber-300">🔍 External research required</p>
                  )}
                </div>
              )}
              {mission.workspace_uri && (
                <div className="rounded border border-emerald-700 bg-emerald-900/20 p-3 text-sm">
                  📁 <b>Everything is in one place:</b>{" "}
                  <a className="text-emerald-300 underline" href={mission.workspace_uri} target="_blank" rel="noreferrer">
                    {mission.workspace_uri}
                  </a>
                </div>
              )}
              {mission.nodes.filter((n: any) => n.status === "WAITING_APPROVAL").map((n: any) => (
                <div key={n.node_id} className="flex items-center gap-3 rounded border border-amber-700 bg-amber-900/20 p-3 text-sm">
                  <span className="text-amber-300">{n.capability_id} needs your approval</span>
                  <button onClick={() => decide(n.node_id, true)} className="rounded bg-emerald-600 px-3 py-1 text-xs font-bold hover:bg-emerald-500">Approve</button>
                  <button onClick={() => decide(n.node_id, false)} className="rounded bg-red-700 px-3 py-1 text-xs font-bold hover:bg-red-600">Reject</button>
                </div>
              ))}
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <Panel t="Artifacts">
                  {mission.artifacts.length === 0 && <p className="text-xs text-zinc-500">No artifacts yet.</p>}
                  {mission.artifacts.map((a: any) => (
                    <p key={a.artifact_id} className="mb-1 text-xs text-zinc-300">
                      <span className="text-emerald-400">{a.type}</span> · <span className="text-zinc-500">{a.uri}</span>
                    </p>
                  ))}
                </Panel>
                <Panel t="Action Receipts">
                  {mission.receipts.length === 0 && <p className="text-xs text-zinc-500">No receipts yet.</p>}
                  {mission.receipts.map((r: any) => (
                    <p key={r.receipt_id} className="mb-1 text-xs text-zinc-300">
                      {r.capability_id} · <span className={r.policy_decision === "ALLOW" ? "text-emerald-400" : "text-amber-400"}>{r.policy_decision}</span> · ${r.cost_usd}
                    </p>
                  ))}
                </Panel>
              </div>
              {TERMINAL.includes(mission.state) && (
                <div className="flex gap-2">
                  <button onClick={forgeNow} className="rounded bg-amber-600 px-4 py-2 text-sm font-bold hover:bg-amber-500">⚒ Forge workflow</button>
                  <button onClick={replayNow} className="rounded bg-zinc-700 px-4 py-2 text-sm font-bold hover:bg-zinc-600">↺ Replay</button>
                </div>
              )}
            </div>
          )}

          {tab === "dag" && <DAGView nodes={mission.nodes} onSelect={setSelectedNode} />}
          {tab === "timeline" && <TimeTravel events={events} nodes={mission.nodes} />}
          {tab === "evidence" && <EvidenceView evidence={mission.evidence} artifacts={mission.artifacts} />}

          {tab === "security" && (
            <div className="space-y-1">
              {auditTrail.length === 0 && <p className="text-sm text-zinc-500">No audit events recorded.</p>}
              {auditTrail.map((a) => (
                <p key={a.entry_id} className={`text-xs ${a.severity === "ALERT" ? "text-red-400" : a.severity === "WARN" ? "text-amber-300" : "text-zinc-400"}`}>
                  <span className="font-bold">[{a.kind}]</span> {a.title} — {a.detail}
                </p>
              ))}
            </div>
          )}

          {tab === "learning" && (
            <div className="space-y-4">
              <div className="flex gap-2">
                <input value={teach} onChange={(e) => setTeach(e.target.value)}
                  placeholder='Teach NEXORA a rule — e.g. "Always require my approval before scheduling meetings."'
                  className="flex-1 rounded border border-sky-800 bg-zinc-900 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none" />
                <button onClick={sendTeach} className="rounded bg-sky-600 px-4 py-2 text-sm font-bold hover:bg-sky-500">Teach</button>
              </div>
              <Panel t="Memory & Forged Workflows">
                {memoryList.length === 0 && workflows.length === 0 && <p className="text-xs text-zinc-500">No memories or workflows yet.</p>}
                {memoryList.slice(-6).map((m: any) => (
                  <p key={m.memory_id} className="mb-1 text-xs text-zinc-400">
                    <span className="text-sky-400">[{m.type}/{m.scope}]</span> {m.content}{m.effect ? ` → ${m.effect}` : ""}
                  </p>
                ))}
                {workflows.slice(-3).map((w: any) => (
                  <p key={w.template_id} className="mb-1 text-xs text-amber-300">⚒ {w.name} · ${w.expected_cost_usd}</p>
                ))}
              </Panel>
            </div>
          )}
        </>
      )}

      {selectedNode && mission && (
        <WhyModal node={selectedNode} mission={mission} onClose={() => setSelectedNode(null)} />
      )}
    </main>
  );
}

function Panel({ t, children }: { t: string; children: any }) {
  return (
    <section className="rounded border border-zinc-800 bg-zinc-900/60 p-4">
      <h2 className="mb-3 text-xs font-bold tracking-widest text-zinc-400">{t.toUpperCase()}</h2>
      {children}
    </section>
  );
}