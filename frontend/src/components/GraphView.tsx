import { useMemo, useState } from 'react';
import type { Graph, GraphNode } from '../api/types';
import { layoutGraph, NODE_COLORS, nodeColor } from '../lib/graphLayout';

const W = 900;
const H = 620;

/** Lightweight SVG force-directed view of the landscape knowledge graph. */
export function GraphView({ graph, onActivate }: { graph: Graph; onActivate?: (n: GraphNode) => void }) {
  const types = useMemo(() => Array.from(new Set(graph.nodes.map((n) => n.type))).sort(), [graph.nodes]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [focus, setFocus] = useState<GraphNode | null>(null);
  const nodes = useMemo(() => graph.nodes.filter((n) => !hidden.has(n.type)), [graph.nodes, hidden]);
  const ids = useMemo(() => new Set(nodes.map((n) => n.id)), [nodes]);
  const edges = useMemo(() => graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target)), [graph.edges, ids]);
  const pos = useMemo(() => layoutGraph(nodes, edges, W, H), [nodes, edges]);
  const neighbours = useMemo(() => {
    if (!focus) return null;
    const s = new Set<string>([focus.id]);
    for (const e of edges) {
      if (e.source === focus.id) s.add(e.target);
      if (e.target === focus.id) s.add(e.source);
    }
    return s;
  }, [focus, edges]);

  return (
    <div className="stack">
      <fieldset>
        <legend>Node types (toggle to show or hide)</legend>
        <div className="legend">
          {types.map((t) => (
            <label key={t} className="checkbox">
              <input
                type="checkbox"
                checked={!hidden.has(t)}
                onChange={() =>
                  setHidden((h) => {
                    const n = new Set(h);
                    if (n.has(t)) n.delete(t);
                    else n.add(t);
                    return n;
                  })
                }
              />
              <svg width="12" height="12" aria-hidden>
                <circle cx="6" cy="6" r="5" fill={NODE_COLORS[t] ?? NODE_COLORS.other} />
              </svg>
              {t.replace(/_/g, ' ')} ({graph.nodes.filter((n) => n.type === t).length})
            </label>
          ))}
          <span className="row" style={{ gap: 4 }}>
            <svg width="14" height="14" aria-hidden>
              <circle cx="7" cy="7" r="5" fill={NODE_COLORS.asset} stroke={NODE_COLORS.customer} strokeWidth="3" />
            </svg>
            Your (customer) asset - double ring
          </span>
        </div>
      </fieldset>
      <div className="grid grid-main-side">
        <svg className="graph-svg" viewBox={`0 0 ${W} ${H}`} role="group" aria-label={`Landscape graph with ${nodes.length} nodes and ${edges.length} relationships`}>
          <g>
            {edges.map((e) => {
              const a = pos.get(e.source);
              const b = pos.get(e.target);
              if (!a || !b) return null;
              const dim = neighbours && !(neighbours.has(e.source) && neighbours.has(e.target));
              return (
                <line
                  key={e.id}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke={e.predicate === 'competes_with' ? '#b42318' : '#98a2b3'}
                  strokeWidth={e.predicate === 'competes_with' ? 1.8 : 1}
                  strokeDasharray={e.status === 'verified' || e.method === 'source' ? undefined : '4 3'}
                  opacity={dim ? 0.15 : 0.8}
                >
                  <title>{e.predicate}</title>
                </line>
              );
            })}
          </g>
          <g>
            {nodes.map((n) => {
              const p = pos.get(n.id);
              if (!p) return null;
              const isCustomer = n.role === 'customer';
              const r = n.type === 'asset' ? (isCustomer ? 12 : 9) : 6;
              const dim = neighbours && !neighbours.has(n.id);
              const showLabel = n.type === 'asset' || n.type === 'company' || focus?.id === n.id || (neighbours?.has(n.id) ?? false);
              return (
                <g
                  key={n.id}
                  className="graph-node"
                  transform={`translate(${p.x},${p.y})`}
                  tabIndex={0}
                  role="button"
                  aria-label={`${n.type.replace(/_/g, ' ')}: ${n.label}${isCustomer ? ' (your asset)' : ''}`}
                  opacity={dim ? 0.3 : 1}
                  onMouseEnter={() => setFocus(n)}
                  onFocus={() => setFocus(n)}
                  onClick={() => onActivate?.(n)}
                  onKeyDown={(ev) => {
                    if (ev.key === 'Enter' || ev.key === ' ') {
                      ev.preventDefault();
                      onActivate?.(n);
                    }
                  }}
                >
                  <circle r={r} fill={nodeColor(n)} stroke={isCustomer ? NODE_COLORS.customer : '#fff'} strokeWidth={isCustomer ? 4 : 1.5} />
                  {showLabel ? (
                    <text y={-r - 4} textAnchor="middle" fontSize={n.type === 'asset' ? 12 : 10} fontWeight={n.type === 'asset' ? 700 : 400} fill="#152033">
                      {n.label.length > 28 ? `${n.label.slice(0, 26)}...` : n.label}
                    </text>
                  ) : null}
                </g>
              );
            })}
          </g>
        </svg>
        <aside className="card" aria-live="polite">
          {focus ? (
            <div className="stack-sm">
              <span className="badge badge-neutral" style={{ alignSelf: 'flex-start' }}>
                {focus.type.replace(/_/g, ' ')}
                {focus.role ? ` - ${focus.role}` : ''}
              </span>
              <strong>{focus.label}</strong>
              <h3 className="small" style={{ marginTop: 8 }}>
                Relationships
              </h3>
              <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
                {edges
                  .filter((e) => e.source === focus.id || e.target === focus.id)
                  .slice(0, 20)
                  .map((e) => {
                    const other = graph.nodes.find((x) => x.id === (e.source === focus.id ? e.target : e.source));
                    return (
                      <li key={e.id}>
                        {e.source === focus.id ? `${e.predicate} -> ` : `<- ${e.predicate} `}
                        {other?.label ?? '?'} <span className="muted">({e.status})</span>
                      </li>
                    );
                  })}
              </ul>
              {focus.type === 'asset' ? <p className="tiny muted">Press Enter or click to open the asset.</p> : null}
            </div>
          ) : (
            <p className="small muted">Hover or focus a node (Tab) to see its relationships. Red edges are competes-with mappings; dashed edges are inferred or unverified.</p>
          )}
        </aside>
      </div>
    </div>
  );
}
