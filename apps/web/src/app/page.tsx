"use client";
import { useEffect, useRef, useState } from "react";
import CommandCenter from "@/components/CommandCenter";
import TechnicalDetails from "@/components/TechnicalDetails";
import WhyModal from "@/components/WhyModal";
import { useVoice } from "@/hooks/useVoice";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TERMINAL = ["COMPLETED", "FAILED", "PARTIAL_SUCCESS"];

// Built-in scenarios — every one runs end to end and is verified against a contract.
const SCENARIOS = [
  // Business & Work
  { label: "🚀 Product Launch", goal: "We launch our new app next Friday. Prepare the launch pack: a go-to-market brief, a budget spreadsheet, an investor pitch deck, and a launch announcement email." },
  { label: "🚨 Customer Escalation", goal: "A customer sent a screenshot of a production error. Analyze the screenshot, estimate the impact, write an incident report, and create follow-up tasks." },
  { label: "📊 Weekly Review", goal: "Search my emails and Drive files, read the metrics sheet, and write this week's business review document." },
  { label: "📧 Email Summary", goal: "Search my inbox for recent emails and write a short summary of what I missed." },
  // Travel & Lifestyle
  { label: "🏝 Dream Trip", goal: "I want to visit the best island in the world. Recommend where to go and prepare a travel brief with an inspiring photo." },
  { label: "🎧 Island + Audio Guide", goal: "Recommend the best island in the world — a written brief, a photo, and a spoken audio narration of the top picks." },
  { label: "🗺 Kyoto in 3 Days", goal: "Plan 3 days in Kyoto: a travel guide document, a day-by-day slide deck, and an itemised budget spreadsheet in USD." },
  // Learning & Development
  { label: "🤖 Learn AI", goal: "Write me a practical plan to learn AI in 2026 — a single study-plan document with curated resources and a weekly schedule." },
  { label: "🎙️ Audio AI Briefing", goal: "Give me an audio briefing about the most important AI developments this week." },
  { label: "📈 Career Growth", goal: "Help me get promoted to senior engineer in 6 months. Write a skill-development roadmap." },
  // Personal Finance
  { label: "🏠 House Down Payment", goal: "Create a budget plan to save for a house down payment. I earn $80k a year." },
  { label: "💰 Wealth Strategy", goal: "How do I build wealth? Give me an honest, research-based strategy document." },
  // Creative
  { label: "👻 Commercial Viability", goal: "Evaluate whether a mobile game called Ghost Run can succeed commercially — a viability report, a market-research summary, and a one-page pitch." },
  { label: "📚 Short Story", goal: "Write a short story about time travel with real character development and a plot twist, plus a concept image for the protagonist." },
];

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
  const [goal, setGoal] = useState(SCENARIOS[6].goal); // Default: Kyoto in 3 Days
  const [intervention, setIntervention] = useState("");
  const [teach, setTeach] = useState("");
  const [mission, setMission] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [auditTrail, setAuditTrail] = useState<any[]>([]);
  const [memoryList, setMemoryList] = useState<any[]>([]);
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<any | null>(null);
  const [gConnected, setGConnected] = useState<boolean | null>(null);
  const [cfg, setCfg] = useState<any>(null);
  useEffect(() => { safeGet(`${API}/api/v1/config`).then(setCfg); }, []);

  // Phase 12: Execution mode selector (MOCK demo vs LIVE real workspace)
  const [execMode, setExecMode] = useState<"MOCK" | "LIVE">("MOCK");

  // Phase 9.2: Attachment & Voice State
  const [attachment, setAttachment] = useState<any | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const voice = useVoice((text) => setGoal(text));

  // Phase 22: Standing instructions (scheduled missions)
  const [schedules, setSchedules] = useState<any[]>([]);
  const [showSchedule, setShowSchedule] = useState(false);
  const [scheduleCadence, setScheduleCadence] = useState("weekdays");
  const refreshSchedules = async () => {
    const s = await safeGet(`${API}/api/v1/schedules`);
    if (s) setSchedules(s);
  };
  useEffect(() => { refreshSchedules(); }, []);
  const addSchedule = async () => {
    if (!goal.trim()) return;
    await fetch(`${API}/api/v1/schedules`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal, cadence: scheduleCadence, hour_utc: 7, execution_mode: execMode }),
    });
    setShowSchedule(false);
    refreshSchedules();
  };
  const runSchedule = async (id: string) => {
    const r = await fetch(`${API}/api/v1/schedules/${id}/run`, { method: "POST" });
    if (r.ok) { const d = await r.json(); refresh(d.mission_id); setMission({ mission_id: d.mission_id, state: "EXECUTING", nodes: [] }); }
    refreshSchedules();
  };
  const deleteSchedule = async (id: string) => {
    await fetch(`${API}/api/v1/schedules/${id}`, { method: "DELETE" });
    refreshSchedules();
  };

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
      ws = new WebSocket(`${API.replace(/^http/, "ws")}/api/v1/missions/${mid}/ws`);
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
        body: JSON.stringify({ goal, execution_mode: execMode, attachment, background: true }),
      });
      if (!r.ok) {
        const detail = await r.json().catch(() => null);
        throw new Error(detail?.detail || `API error ${r.status}`);
      }
      setMission(await r.json());
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

  return (
    <main className="min-h-screen bg-zinc-950 p-6 font-mono text-zinc-100 lg:p-10">
      <header className="mb-6 text-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/brand/wordmark-dark.svg" alt="NEXORA" className="mx-auto h-14 lg:h-16" />
        <p className="mt-3 text-base text-zinc-300">
          One goal in. A <span className="text-emerald-400">verified workspace of real work</span> out.
        </p>
        <p className="mx-auto mt-1 max-w-xl text-xs text-zinc-500">
          A workforce of Gemini&nbsp;3.5 agents on Google&nbsp;ADK plans the work, does it in the
          background, checks it against a contract, and files every deliverable into one Drive folder.
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-1.5 text-[11px] text-zinc-500">
          {["Understand", "Discover", "Plan", "Execute", "Verify"].map((s, i) => (
            <span key={s} className="flex items-center gap-1.5">
              {i > 0 && <span className="text-zinc-700">→</span>}
              <span className="rounded-full border border-zinc-800 bg-zinc-900/60 px-2.5 py-0.5">{s}</span>
            </span>
          ))}
        </div>

        {/* Live Google-stack badges — resolved from the running config */}
        {cfg?.badges && (
          <div className="mx-auto mt-4 flex max-w-3xl flex-wrap items-center justify-center gap-1.5">
            {cfg.badges.map((b: any) => (
              <span key={b.label}
                title={`${b.label}: ${b.value}`}
                className={`rounded border px-2 py-0.5 text-[10px] font-bold tracking-wide ${
                  b.on
                    ? "border-emerald-700/70 bg-emerald-950/40 text-emerald-300"
                    : "border-zinc-800 bg-zinc-900/50 text-zinc-500"
                }`}>
                {b.value}
              </span>
            ))}
          </div>
        )}
      </header>

      <div className="mx-auto max-w-3xl">
        {/* Phase 12: Execution mode selector */}
        <section className="mb-4 flex justify-center gap-2">
          <button onClick={() => setExecMode("MOCK")}
            className={`rounded-full border px-4 py-1.5 text-xs font-bold ${execMode === "MOCK" ? "border-sky-500 bg-sky-900/40 text-sky-200" : "border-zinc-700 text-zinc-500 hover:border-zinc-500"}`}>
            🧪 MOCK (demo)
          </button>
          <button onClick={() => setExecMode("LIVE")}
            className={`rounded-full border px-4 py-1.5 text-xs font-bold ${execMode === "LIVE" ? "border-emerald-500 bg-emerald-900/40 text-emerald-200" : "border-zinc-700 text-zinc-500 hover:border-zinc-500"}`}>
            🔴 LIVE (real Google)
          </button>
        </section>
        {execMode === "LIVE" && gConnected === false && (
          <p className="mb-3 text-center text-xs text-amber-400">
            ⚠️ LIVE mode needs a Google connection —{" "}
            <a href={`${API}/api/v1/auth/google`} className="underline">connect now</a>.
          </p>
        )}

        {/* Scenario chips */}
        <section className="mb-4 flex flex-wrap justify-center gap-2">
          {SCENARIOS.map((s) => (
            <button key={s.label} onClick={() => setGoal(s.goal)}
              className={`rounded-full border px-3 py-1 text-xs ${goal === s.goal ? "border-emerald-500 bg-emerald-900/40 text-emerald-200" : "border-zinc-700 text-zinc-400 hover:border-zinc-500"}`}>
              {s.label}
            </button>
          ))}
        </section>

        {/* Goal Input + Attach + Voice + Launch */}
        <section className="mb-4 flex gap-2">
          <input value={goal} onChange={(e) => setGoal(e.target.value)}
            placeholder="What should NEXORA accomplish?"
            className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-4 py-3 text-sm focus:border-emerald-500 focus:outline-none" />

          <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={onFile} />

          <button onClick={() => fileRef.current?.click()} title="Attach a screenshot/image"
            className={`rounded border px-4 py-3 text-sm ${attachment ? "border-sky-500 bg-sky-900/30 text-sky-300" : "border-zinc-700 text-zinc-400 hover:border-zinc-500"}`}>
            📎
          </button>

          <button onClick={voice.toggle} disabled={!voice.supported}
            title={voice.supported ? "Speak your goal" : "Voice not supported in this browser (use Chrome/Edge)"}
            className={`rounded border px-4 py-3 text-sm ${voice.listening ? "animate-pulse border-red-500 bg-red-900/30 text-red-400" : "border-zinc-700 text-zinc-400 hover:border-zinc-500 disabled:opacity-50"}`}>
            🎤
          </button>

          <button onClick={launch} disabled={loading}
            className="rounded bg-emerald-500 px-6 py-3 text-sm font-bold text-zinc-950 hover:bg-emerald-400 disabled:opacity-50">
            {loading ? "Launching…" : "Launch"}
          </button>

          <button onClick={() => setShowSchedule((v) => !v)} title="Run this goal on a schedule"
            className={`rounded border px-4 py-3 text-sm ${showSchedule ? "border-amber-500 bg-amber-900/30 text-amber-300" : "border-zinc-700 text-zinc-400 hover:border-zinc-500"}`}>
            🗓
          </button>
        </section>

        {showSchedule && (
          <section className="mb-4 flex items-center gap-2 rounded border border-amber-800 bg-amber-950/20 p-3 text-xs">
            <span className="text-amber-300">Run this goal</span>
            <select value={scheduleCadence} onChange={(e) => setScheduleCadence(e.target.value)}
              className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-zinc-200">
              <option value="once">once (in ~1 min)</option>
              <option value="daily">every day</option>
              <option value="weekdays">every weekday</option>
              <option value="weekly">every week</option>
              <option value="monthly">every month</option>
            </select>
            <span className="text-zinc-500">at 07:00 UTC · {execMode}</span>
            <button onClick={addSchedule} className="rounded bg-amber-600 px-3 py-1 font-bold text-zinc-950 hover:bg-amber-500">
              Add standing instruction
            </button>
          </section>
        )}

        {schedules.length > 0 && (
          <section className="mb-4 rounded border border-zinc-800 bg-zinc-900/40 p-3">
            <p className="mb-2 text-xs font-bold tracking-widest text-zinc-500">STANDING INSTRUCTIONS · {schedules.length}</p>
            <div className="space-y-1.5">
              {schedules.map((s) => (
                <div key={s.schedule_id} className="flex items-center gap-2 text-xs">
                  <span className="rounded bg-amber-900/40 px-2 py-0.5 text-amber-300">{s.cadence}</span>
                  <span className="flex-1 truncate text-zinc-300">{s.goal}</span>
                  <span className="text-zinc-600">next {new Date(s.next_run).toLocaleString()}{s.run_count > 0 ? ` · ran ${s.run_count}×` : ""}</span>
                  <button onClick={() => runSchedule(s.schedule_id)} className="rounded bg-zinc-700 px-2 py-0.5 hover:bg-zinc-600">Run now</button>
                  <button onClick={() => deleteSchedule(s.schedule_id)} className="text-zinc-600 hover:text-red-400">✕</button>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Status indicators */}
        {attachment && (
          <p className="mb-3 flex items-center justify-center gap-2 text-xs text-sky-300">
            📎 Attached: <span className="font-bold">{attachment.name}</span>
            <span className="text-zinc-500">— NEXORA will analyze it using Gemini vision.</span>
          </p>
        )}
        {voice.listening && (
          <p className="mb-3 flex items-center justify-center gap-2 text-xs text-red-400 animate-pulse">
            🎤 Listening… speak your goal, then click Launch.
          </p>
        )}

        {error && (
          <p className="mb-4 rounded border border-red-800 bg-red-900/20 p-2 text-center text-sm text-red-400">
            Error: {error}
          </p>
        )}

        {/* Intervention bar (when running) */}
        {mission && !TERMINAL.includes(mission.state) && (
          <section className="mb-4 flex gap-2">
            <input value={intervention} onChange={(e) => setIntervention(e.target.value)}
              placeholder='Change the mission live — e.g. "Stop all external communication."'
              className="flex-1 rounded border border-violet-800 bg-zinc-900 px-3 py-2 text-sm focus:border-violet-500 focus:outline-none" />
            <button onClick={sendIntervention} className="rounded bg-violet-600 px-4 py-2 text-sm font-bold text-zinc-950 hover:bg-violet-500">
              Intervene
            </button>
          </section>
        )}

        {/* Approval cards (when waiting) */}
        {mission && mission.nodes?.filter((n: any) => n.status === "WAITING_APPROVAL").length > 0 && (
          <section className="mb-4 space-y-2">
            {mission.nodes
              .filter((n: any) => n.status === "WAITING_APPROVAL")
              .map((n: any) => (
                <div key={n.node_id} className="flex items-center gap-3 rounded border border-amber-700 bg-amber-900/20 p-3 text-sm">
                  <span className="text-amber-300">{n.capability_id} needs your approval</span>
                  <button onClick={() => decide(n.node_id, true)} className="rounded bg-emerald-600 px-3 py-1 text-xs font-bold hover:bg-emerald-500">Approve</button>
                  <button onClick={() => decide(n.node_id, false)} className="rounded bg-red-700 px-3 py-1 text-xs font-bold hover:bg-red-600">Reject</button>
                </div>
              ))}
          </section>
        )}

        {/* Command Center (main view) */}
        <CommandCenter
          mission={mission}
          events={events}
          onShowDetails={() => {
            const el = document.getElementById("technical-details");
            if (el) {
              el.scrollIntoView({ behavior: "smooth" });
              const btn = el.querySelector("button");
              if (btn) (btn as HTMLButtonElement).click();
            }
          }}
        />

        {/* Technical Details (expandable, secondary) */}
        {mission && (
          <div id="technical-details">
            <TechnicalDetails
              mission={mission}
              events={events}
              auditTrail={auditTrail}
              memoryList={memoryList}
              workflows={workflows}
              teach={teach}
              setTeach={setTeach}
              sendTeach={sendTeach}
              forgeNow={forgeNow}
              replayNow={replayNow}
              setSelectedNode={setSelectedNode}
            />
          </div>
        )}

        {/* Footer links */}
        <footer className="mt-8 flex flex-col items-center gap-2 text-xs text-zinc-500">
          <div className="flex justify-center gap-6">
            <a href="/scenarios" className="underline hover:text-zinc-300">Scenario Gallery</a>
            <a href="/explorer" className="underline hover:text-zinc-300">Capability Explorer</a>
            {gConnected === false && (
              <a href={`${API}/api/v1/auth/google`} className="text-sky-400 underline">🔗 Connect Google</a>
            )}
            {gConnected === true && <span className="text-emerald-400">● Google connected</span>}
          </div>
          <p className="text-center">
            Cost: Imagen ~$0.04/image • Lyria ~$0.02-0.05/audio • Gemini ~$0.001/plan
          </p>
        </footer>
      </div>

      {selectedNode && mission && (
        <WhyModal node={selectedNode} mission={mission} onClose={() => setSelectedNode(null)} />
      )}
    </main>
  );
}