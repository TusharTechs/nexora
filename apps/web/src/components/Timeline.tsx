"use client";
import { useMemo, useState } from "react";

type Ev = { event_type: string; timestamp: string; payload: any };

export default function Timeline({ events }: { events: Ev[] }) {
  const sorted = useMemo(
    () => [...events].sort((a, b) => a.timestamp.localeCompare(b.timestamp)), [events]);
  const [idx, setIdx] = useState(Math.max(0, sorted.length - 1));
  if (!sorted.length) return <p className="text-sm text-zinc-500">No events yet.</p>;
  const upto = sorted.slice(0, idx + 1);
  const current = sorted[idx];
  return (
    <div>
      <input type="range" min={0} max={sorted.length - 1} value={idx}
        onChange={(e) => setIdx(Number(e.target.value))} className="w-full accent-emerald-400" />
      <div className="mb-3 mt-1 flex justify-between text-[10px] text-zinc-500">
        <span>{new Date(sorted[0].timestamp).toLocaleTimeString()}</span>
        <span className="text-emerald-400">{current.event_type}</span>
        <span>{new Date(sorted[sorted.length - 1].timestamp).toLocaleTimeString()}</span>
      </div>
      <div className="max-h-72 space-y-1 overflow-y-auto">
        {upto.map((e, i) => (
          <p key={i} className={`text-xs ${i === idx ? "rounded bg-emerald-900/40 px-1 text-emerald-200" : "text-zinc-400"}`}>
            <span className="text-zinc-600">{new Date(e.timestamp).toLocaleTimeString()}</span> {e.event_type}
          </p>
        ))}
      </div>
    </div>
  );
}