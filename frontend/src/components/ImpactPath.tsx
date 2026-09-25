import { Fragment } from 'react';
import { ArrowRight } from 'lucide-react';
import type { ImpactMapping, PathHop } from '../api/types';

function label(l: string | undefined, id: string): string {
  if (!l) return id.slice(0, 8);
  return l.length > 60 ? `${l.slice(0, 57)}...` : l;
}

/** Graph path rendered as a readable chain: XD-101 -competes_with-> CA-201 -evaluated_in-> NCT... */
export function PathChain({ path, customerId }: { path: PathHop[]; customerId?: string }) {
  if (!path.length) return <span className="muted small">No graph path recorded.</span>;
  const text = [path[0].from_label ?? path[0].from, ...path.map((h) => `${h.predicate} ${h.to_label ?? h.to}`)].join(' -> ');
  return (
    <ol className="path" aria-label={`Impact path: ${text}`}>
      <li className={`path-node ${path[0].from === customerId ? 'customer' : ''}`} title={path[0].from_label}>
        {label(path[0].from_label, path[0].from)}
      </li>
      {path.map((h, i) => (
        <Fragment key={`${h.edge_id ?? i}-${i}`}>
          <li className="path-edge" title={`${h.method ?? ''}${h.confidence !== undefined ? ` (confidence ${h.confidence.toFixed(2)})` : ''}`}>
            <span aria-hidden>-</span>
            {h.predicate}
            <ArrowRight size={13} aria-hidden />
          </li>
          <li className="path-node" title={h.to_label}>
            {label(h.to_label, h.to)}
          </li>
        </Fragment>
      ))}
    </ol>
  );
}

export function ImpactList({ impacts }: { impacts: ImpactMapping[] }) {
  return (
    <ul className="list-plain">
      {impacts.map((m, i) => (
        <li key={`${m.asset_id}-${i}`} className="stack-sm">
          <div className="row-between">
            <strong>{m.asset_name}</strong>
            <span className="badge badge-info">Proximity {m.proximity.toFixed(2)}</span>
          </div>
          <PathChain path={m.path} customerId={m.asset_id} />
          <p className="small muted" style={{ margin: 0 }}>
            {m.rationale}
          </p>
          {m.detail?.dimensions ? (
            <details>
              <summary className="small">Proximity dimensions{m.detail.rule ? ` (rule: ${m.detail.rule})` : ''}</summary>
              <div className="table-wrap" style={{ marginTop: 6 }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Dimension</th>
                      <th scope="col" className="num">
                        Weight
                      </th>
                      <th scope="col" className="num">
                        Score
                      </th>
                      <th scope="col">Shared</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(m.detail.dimensions).map(([k, d]) => (
                      <tr key={k}>
                        <td>{k.replace(/_/g, ' ')}</td>
                        <td className="num">{d.weight.toFixed(2)}</td>
                        <td className="num">{d.known ? d.score.toFixed(2) : 'Unknown'}</td>
                        <td>{d.shared.length ? d.shared.join(', ') : <span className="muted">none</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
