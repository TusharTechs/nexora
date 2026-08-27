"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import DAGView from "@/components/DAGView";

type Ev = { event_type: string; timestamp: string; payload: any };

const STATUS_FOR: Record<string, string> = {
  "MISSION.NODE.STARTED": "RUNNING",
  "MISSION.NODE.COMPLETED": "SUCCESS",
  "MISSION.NODE.SKIPPED": "SKIPPED",
  "MISSION.NODE.FAILED": "FAILED",
  "MISSION.APPROVAL_REQUESTED": "WAITING_APPROVAL",
};

export default function TimeTravel({ events, nodes }: { events: Ev[]; nodes: any[] }) {
  const sorted = useMemo(() => [...events].sort((a, b) => a.timestamp.localeCompare(b.timestamp)), [events]);
  const [idx, setIdx] = useState(sorted.length ? sorted.length - 1 : 0);
  const [playing, setPlaying] = useState(false);
  const timer = useRef<any>(null);

  useEffect(() => {
    if (!playing) { if (timer.current) clearInterval(timer.current); return; }
    timer.current = setInterval(() => {
      setIdx((i) => {
        if (i >= sorted.length - 1) { setPlaying(false); return i; }
        return i + 1;
      });
    }, 500);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [playing, sorted.length]);

  // Reconstruct node statuses purely from events[0..idx] (ADR-052)
  const historical = useMemo(() => {
    const status: Record<string, string> = {};
    for (const e of sorted.slice(0, idx + 1)) {
      const nid = e.payload?.node_id;
      const s = STATUS_FOR[e.event_type];
      if (nid && s) status[nid] = s;
    }
    return nodes.map((n) => ({ ...n, status: status[n.node_id] ?? "PENDING" }));
  }, [sorted, idx, nodes]);

  if (!sorted.length) return <p className="text-sm text-zinc-500">No events yet — launch a mission.</p>;
  const current = sorted[idx];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button
          onClick={() => { if (idx >= sorted.length - 1) setIdx(0); setPlaying((p) => !p); }}
          className="rounded bg-emerald-600 px-3 py-1 text-sm font-bold hover:bg-emerald-500">
          {playing ? "⏸ Pause" : "▶ Watch the magic"}
        </button>
        <input type="range" min={0} max={sorted.length - 1} value={idx}
          onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }}
          className="flex-1 accent-emerald-400" />
        <span className="text-xs text-zinc-400">{idx + 1}/{sorted.length}</span>
      </div>
      <p className="text-xs text-emerald-300">
        {new Date(current.timestamp).toLocaleTimeString()} — {current.event_type}
      </p>
      <DAGView nodes={historical} onSelect={() => {}} />
    </div>
  );
}