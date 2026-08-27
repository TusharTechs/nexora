"use client";
import { useMemo } from "react";

type DagNode = {
  node_id: string; capability_id: string; status: string;
  depends_on: string[]; condition?: any; replaced_by?: string | null;
};

export const STATUS_COLOR: Record<string, string> = {
  SUCCESS: "#34d399", FAILED: "#f87171", SKIPPED: "#52525b",
  WAITING_APPROVAL: "#fbbf24", RUNNING: "#38bdf8", PENDING: "#71717a",
};

const NODE_W = 180, NODE_H = 46, GAP_X = 70, GAP_Y = 26;

function layout(nodes: DagNode[]) {
  const byId = new Map(nodes.map((n) => [n.node_id, n]));
  const depth: Record<string, number> = {};
  const d = (id: string): number => {
    if (depth[id] !== undefined) return depth[id];
    const n = byId.get(id);
    if (!n || !n.depends_on?.length) { depth[id] = 0; return 0; }
    depth[id] = 1 + Math.max(...n.depends_on.map(d));
    return depth[id];
  };
  nodes.forEach((n) => d(n.node_id));
  const layers: DagNode[][] = [];
  nodes.forEach((n) => { (layers[depth[n.node_id]] ||= []).push(n); });
  const positions: Record<string, { x: number; y: number }> = {};
  layers.forEach((layer, li) =>
    layer.forEach((n, ni) => {
      positions[n.node_id] = { x: li * (NODE_W + GAP_X) + 10, y: ni * (NODE_H + GAP_Y) + 10 };
    }));
  const edges = nodes.flatMap((n) => (n.depends_on || []).map((dep) => ({ from: dep, to: n.node_id })));
  const width = layers.length * (NODE_W + GAP_X) + 20;
  const height = Math.max(1, ...layers.map((l) => l.length)) * (NODE_H + GAP_Y) + 20;
  return { edges, positions, width, height };
}

export default function DAGView({ nodes, onSelect }: { nodes: DagNode[]; onSelect: (n: DagNode) => void }) {
  const { edges, positions, width, height } = useMemo(() => layout(nodes), [nodes]);
  if (!nodes.length) return <p className="text-sm text-zinc-500">No plan yet.</p>;
  return (
    <div className="overflow-auto rounded border border-zinc-800 bg-zinc-950/60 p-3">
      <svg width={width} height={height}>
        {edges.map((e, i) => {
          const a = positions[e.from], b = positions[e.to];
          if (!a || !b) return null;
          const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2;
          const mx = (x1 + x2) / 2;
          return <path key={i} d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
            fill="none" stroke="#3f3f46" strokeWidth="1.5" />;
        })}
        {nodes.map((n) => {
          const p = positions[n.node_id];
          const c = STATUS_COLOR[n.status] || "#71717a";
          return (
            <g key={n.node_id} transform={`translate(${p.x},${p.y})`} className="cursor-pointer"
               onClick={() => onSelect(n)}>
              <rect width={NODE_W} height={NODE_H} rx="8" fill="#18181b" stroke={c} strokeWidth="1.5"
                className={n.status === "RUNNING" ? "animate-pulse" : ""} />
              <circle cx="14" cy={NODE_H / 2} r="4" fill={c} />
              <text x="26" y={NODE_H / 2 - 4} fill="#e4e4e7" fontSize="11" fontFamily="monospace">
                {n.capability_id}
              </text>
              <text x="26" y={NODE_H / 2 + 12} fill={c} fontSize="9" fontFamily="monospace">
                [{n.status}]{n.condition ? " ⑂" : ""}{n.replaced_by ? " →" : ""}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-zinc-400">
        {Object.entries(STATUS_COLOR).map(([k, v]) => (
          <span key={k} className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: v }} /> {k}
          </span>
        ))}
      </div>
    </div>
  );
}