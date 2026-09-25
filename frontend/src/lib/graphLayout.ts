import type { GraphEdge, GraphNode } from '../api/types';

export const NODE_COLORS: Record<string, string> = {
  asset: '#1d4ed8',
  customer: '#b42318',
  company: '#475467',
  trial: '#067647',
  publication: '#7a2e98',
  regulatory_event: '#b54708',
  target: '#0e7490',
  indication: '#a15c07',
  mechanism: '#0e7490',
  biomarker: '#9f1ab1',
  other: '#667085',
};

export function nodeColor(n: GraphNode): string {
  return NODE_COLORS[n.type] ?? NODE_COLORS.other;
}

export interface Pt {
  x: number;
  y: number;
}

/** Deterministic force-directed layout (seeded by index; no randomness so layouts are stable). */
export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[], w: number, h: number, iterations = 280): Map<string, Pt> {
  const n = nodes.length;
  const pos = new Map<string, Pt>();
  if (n === 0) return pos;
  const cx = w / 2;
  const cy = h / 2;
  const idx = new Map(nodes.map((nd, i) => [nd.id, i]));
  const xs = new Float64Array(n);
  const ys = new Float64Array(n);
  // Seed: assets/companies on an inner ring, everything else outside.
  nodes.forEach((nd, i) => {
    const inner = nd.type === 'asset' || nd.type === 'company';
    const radius = nd.role === 'customer' ? 0 : inner ? Math.min(w, h) * 0.22 : Math.min(w, h) * 0.4;
    const a = (2 * Math.PI * i) / n;
    xs[i] = cx + radius * Math.cos(a);
    ys[i] = cy + radius * Math.sin(a);
  });
  const links = edges.map((e) => [idx.get(e.source), idx.get(e.target)] as const).filter((l): l is readonly [number, number] => l[0] !== undefined && l[1] !== undefined);
  const k = Math.sqrt((w * h) / n) * 0.55;
  let temp = w / 8;
  for (let it = 0; it < iterations; it++) {
    const dx = new Float64Array(n);
    const dy = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let ddx = xs[i] - xs[j];
        let ddy = ys[i] - ys[j];
        let d2 = ddx * ddx + ddy * ddy;
        if (d2 < 0.01) {
          ddx = 0.1 * (i - j);
          ddy = 0.1;
          d2 = ddx * ddx + ddy * ddy;
        }
        const d = Math.sqrt(d2);
        const f = (k * k) / d;
        dx[i] += (ddx / d) * f;
        dy[i] += (ddy / d) * f;
        dx[j] -= (ddx / d) * f;
        dy[j] -= (ddy / d) * f;
      }
    }
    for (const [a, b] of links) {
      const ddx = xs[a] - xs[b];
      const ddy = ys[a] - ys[b];
      const d = Math.max(0.01, Math.sqrt(ddx * ddx + ddy * ddy));
      const f = (d * d) / k;
      dx[a] -= (ddx / d) * f;
      dy[a] -= (ddy / d) * f;
      dx[b] += (ddx / d) * f;
      dy[b] += (ddy / d) * f;
    }
    for (let i = 0; i < n; i++) {
      // gravity keeps disconnected components on-canvas
      dx[i] += (cx - xs[i]) * 0.02 * k * 0.05;
      dy[i] += (cy - ys[i]) * 0.02 * k * 0.05;
      const d = Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) || 1;
      xs[i] += (dx[i] / d) * Math.min(d, temp);
      ys[i] += (dy[i] / d) * Math.min(d, temp);
    }
    temp *= 0.97;
  }
  // Fit into the viewport with padding.
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (let i = 0; i < n; i++) {
    minX = Math.min(minX, xs[i]);
    maxX = Math.max(maxX, xs[i]);
    minY = Math.min(minY, ys[i]);
    maxY = Math.max(maxY, ys[i]);
  }
  const pad = 70;
  const sx = maxX - minX > 1 ? (w - 2 * pad) / (maxX - minX) : 1;
  const sy = maxY - minY > 1 ? (h - 2 * pad) / (maxY - minY) : 1;
  nodes.forEach((nd, i) => {
    pos.set(nd.id, {
      x: maxX - minX > 1 ? pad + (xs[i] - minX) * sx : cx,
      y: maxY - minY > 1 ? pad + (ys[i] - minY) * sy : cy,
    });
  });
  return pos;
}
