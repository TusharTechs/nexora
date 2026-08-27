"use client";
import { useRouter } from "next/navigation";

const SCENARIOS = [
  { emoji: "💼", title: "Business Launch",
    goal: "I'm starting my new business project tomorrow. Prepare everything I need: business plan doc, learning materials, budget sheet, pitch deck, kickoff meeting, and tasks.",
    builds: ["Business plan (Doc)", "Budget tracker (Sheet)", "Pitch deck (Slides)", "Kickoff meeting (Calendar+Meet)", "Action items (Tasks)"],
    caps: ["docs.create", "sheets.create", "slides.create", "calendar.create_event", "tasks.create"] },
  { emoji: "🚀", title: "Launch Aurora",
    goal: "Prepare everything to launch Product X next Friday: research, budget sheet, meetings, deck, announcement.",
    builds: ["Market research (Doc)", "Budget (Sheet)", "Launch meetings", "Exec deck (Slides)", "Announcement draft (Gmail)"],
    caps: ["docs.create", "sheets.create", "slides.create", "calendar.create_event", "gmail.draft"] },
  { emoji: "🚨", title: "Customer Escalation",
    goal: "A customer sent a screenshot of a production error. Investigate, analyze the screenshot, estimate impact, create the incident report, notify the team, and create follow-up tasks.",
    builds: ["Screenshot analysis (Gemini vision)", "Incident report (Doc)", "Team notify (Chat)", "Follow-ups (Tasks)"],
    caps: ["gmail.search", "multimodal.analyze", "docs.create", "chat.notify", "tasks.create"] },
  { emoji: "📊", title: "Weekly Review",
    goal: "Search emails and drive files, read the metrics sheet, and write the weekly business report.",
    builds: ["Metrics read (Sheet)", "Weekly report (Doc)"],
    caps: ["gmail.search", "drive.search", "sheets.read", "docs.create"] },
];

export default function ScenariosPage() {
  const router = useRouter();
  return (
    <main className="min-h-screen bg-zinc-950 p-8 font-mono text-zinc-100">
      <header className="mb-8 flex items-baseline justify-between">
        <div>
          <h1 className="bg-gradient-to-r from-emerald-400 to-sky-400 bg-clip-text text-3xl font-black tracking-widest text-transparent">
            NEXORA · Scenario Gallery
          </h1>
          <p className="text-sm text-zinc-400">One goal in. A whole organization's work out.</p>
        </div>
        <a href="/" className="text-xs text-zinc-400 underline">← Mission Control</a>
      </header>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {SCENARIOS.map((s) => (
          <section key={s.title} className="flex flex-col rounded-lg border border-zinc-800 bg-zinc-900/60 p-5">
            <h2 className="mb-2 text-lg font-bold text-emerald-300">{s.emoji} {s.title}</h2>
            <p className="mb-3 text-sm text-zinc-300">“{s.goal}”</p>
            <p className="mb-1 text-xs font-bold tracking-widest text-zinc-500">NEXORA WILL BUILD</p>
            <ul className="mb-3 list-inside list-disc text-xs text-zinc-400">
              {s.builds.map((b) => <li key={b}>{b}</li>)}
            </ul>
            <div className="mb-4 flex flex-wrap gap-1">
              {s.caps.map((c) => (
                <span key={c} className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-sky-300">{c}</span>
              ))}
            </div>
            <button onClick={() => router.push(`/?goal=${encodeURIComponent(s.goal)}`)}
              className="mt-auto rounded bg-emerald-500 px-4 py-2 text-sm font-bold text-zinc-950 hover:bg-emerald-400">
              Load in Mission Control →
            </button>
          </section>
        ))}
      </div>
    </main>
  );
}