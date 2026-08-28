"use client";
import { useEffect, useRef, useState } from "react";
import CommandCenter from "@/components/CommandCenter";
import TechnicalDetails from "@/components/TechnicalDetails";
import WhyModal from "@/components/WhyModal";
import { useVoice } from "@/hooks/useVoice";

const API = "http://localhost:8000";
const TERMINAL = ["COMPLETED", "FAILED", "PARTIAL_SUCCESS"];

// Phase 12: Expanded scenario library covering all goal types
const SCENARIOS = [
  // Business & Work
  { label: "💼 Business Launch", goal: "I'm starting my new business project tomorrow. Prepare everything I need: business plan doc, learning materials, budget sheet, pitch deck, kickoff meeting, and tasks." },
  { label: "🚀 Launch Aurora", goal: "Prepare everything to launch Product X next Friday: research, budget sheet, meetings, deck, announcement." },
  { label: "🚨 Customer Escalation", goal: "A customer sent a screenshot of a production error. Investigate, analyze the screenshot, estimate impact, create the incident report, notify the team, and create follow-up tasks." },
  { label: "📊 Weekly Review", goal: "Search emails and drive files, read the metrics sheet, and write the weekly business report." },
  { label: "📧 Email Summary", goal: "Search my inbox for recent emails and create a summary of what I missed." },
  // Travel & Lifestyle (Phase 10: Imagen images)
  { label: "🏝 Dream Trip", goal: "I want to go to the best island in the world. Recommend where I should go and prepare a travel brief with pictures." },
  { label: "🎧 Island + Audio Guide", goal: "Recommend the best island in the world with pictures AND an audio narration of the top picks." },
  // Learning & Development
  { label: "🤖 Learn AI", goal: "Prepare a comprehensive plan to learn AI in 2026, including resources and a study schedule." },
  { label: "🎙️ Audio AI Briefing", goal: "Give me an audio briefing about the most important AI news this week." },
  { label: "📈 Career Growth", goal: "Help me get promoted to senior engineer in 6 months. Create a skill development roadmap." },
  // Personal Finance
  { label: "🏠 House Down Payment", goal: "Create a budget plan to save for a house down payment. I earn $80k/year." },
  { label: "💰 Wealth Strategy", goal: "How do I get rich? Give me an honest, research-based wealth building strategy." },
  // Creative & Demo
  { label: "👻 Ghost Run", goal: "Evaluate whether Ghost Run can succeed commercially and prepare everything I need for launch." },
  { label: "📚 Short Story", goal: "Write a short story about time travel with character development and plot twists." },
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
  const [goal, setGoal] = useState(SCENARIOS[5].goal); // Default: Dream Trip
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

  // Phase 12: Execution mode selector (MOCK demo vs LIVE real workspace)
  const [execMode, setExecMode] = useState<"MOCK" | "LIVE">("MOCK");

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
        body: JSON.stringify({ goal, execution_mode: execMode, attachment }),
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
      <header className="mb-8 text-center">
        <h1 className="bg-gradient-to-r from-emerald-400 to-sky-400 bg-clip-text text-5xl font-black tracking-widest text-transparent">
          NEXORA
        </h1>
        <p className="mt-2 text-sm text-zinc-400">
          One goal in. A verified workspace of real work out.
        </p>
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
        </section>

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