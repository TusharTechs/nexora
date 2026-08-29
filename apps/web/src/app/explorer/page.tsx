"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Capability = {
  capability_id: string;
  name: string;
  description: string;
  provider: string;
  required_api: string;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  estimated_cost_usd: number;
  estimated_latency_ms: number;
  reversible: boolean;
  approval_requirement: "NONE" | "ALWAYS";
  execution_mode_support: string[];
};

const CATEGORIES: Record<string, string[]> = {
  COMMUNICATION: ["gmail.search", "gmail.read", "gmail.draft", "gmail.send", "chat.notify"],
  KNOWLEDGE: ["drive.search", "drive.read", "drive.create_folder", "docs.create", "docs.read", "docs.update",
              "sheets.create", "sheets.read", "sheets.write", "people.search", "multimodal.analyze"],
  OPERATIONS: ["calendar.search", "calendar.availability", "calendar.create_event", "tasks.create", "forms.create"],
  CREATIVE: ["slides.create", "veo.generate_video", "lyria.generate_audio"],
};

function categoryFor(id: string): string {
  for (const [cat, caps] of Object.entries(CATEGORIES)) if (caps.includes(id)) return cat;
  return "OTHER";
}

const RISK_BG = { LOW: "bg-emerald-900/40 border-emerald-700",
                  MEDIUM: "bg-amber-900/40 border-amber-700",
                  HIGH: "bg-red-900/40 border-red-700" };

export default function ExplorerPage() {
  const [caps, setCaps] = useState<Capability[]>([]);
  useEffect(() => {
    fetch(`${API}/api/v1/capabilities`).then((r) => (r.ok ? r.json() : [])).then(setCaps);
  }, []);

  const grouped: Record<string, Capability[]> = {};
  caps.forEach((c) => {
    const cat = categoryFor(c.capability_id);
    (grouped[cat] ||= []).push(c);
  });

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 p-8 font-mono">
      <header className="mb-6 flex items-baseline gap-4">
        <h1 className="text-2xl font-bold tracking-widest text-emerald-400">NEXORA · Capability Network</h1>
        <a href="/" className="text-xs text-zinc-500 underline">← Mission Control</a>
      </header>
      <p className="mb-6 text-sm text-zinc-400">
        Every capability NEXORA can discover and invoke. The Workflow Compiler reasons over these —
        never over raw Google APIs.
      </p>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
        {Object.entries(grouped).map(([cat, list]) => (
          <section key={cat} className="rounded border border-zinc-800 bg-zinc-900/60 p-4">
            <h2 className="mb-3 text-xs font-bold tracking-widest text-zinc-400">{cat}</h2>
            <div className="space-y-2">
              {list.map((c) => (
                <div key={c.capability_id}
                  className={`rounded border p-2 text-xs ${RISK_BG[c.risk_level]}`}>
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-zinc-100">{c.capability_id}</span>
                    <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">
                      {c.required_api}
                    </span>
                  </div>
                  <p className="mt-1 text-zinc-400">{c.name} — {c.description}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]">
                    <Badge label={`risk: ${c.risk_level}`} />
                    <Badge label={`approval: ${c.approval_requirement}`} />
                    <Badge label={`cost: $${c.estimated_cost_usd.toFixed(4)}`} />
                    <Badge label={`~${c.estimated_latency_ms}ms`} />
                    {c.reversible && <Badge label="reversible" tone="emerald" />}
                    {c.execution_mode_support.map((m) => (
                      <Badge key={m} label={m} tone="sky" />
                    ))}
                  </div>
                </div>
              ))}
              {list.length === 0 && <p className="text-xs text-zinc-600">— (Phase 7+)</p>}
            </div>
          </section>
        ))}
      </div>
    </main>
  );
}

function Badge({ label, tone }: { label: string; tone?: string }) {
  const color =
    tone === "emerald" ? "bg-emerald-800 text-emerald-200" :
    tone === "sky"     ? "bg-sky-900 text-sky-200" :
                         "bg-zinc-800 text-zinc-300";
  return <span className={`rounded px-1.5 py-0.5 ${color}`}>{label}</span>;
}