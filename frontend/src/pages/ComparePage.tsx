import { useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, X } from 'lucide-react';
import { api } from '../api/endpoints';
import { StaleBadge } from '../components/Badges';
import { EntityPicker } from '../components/EntityPicker';
import { ExportButtons } from '../components/ExportButtons';
import { ProvenanceCell } from '../components/Provenance';
import { EmptyState, QueryView } from '../components/States';
import { useLandscape } from '../state/landscapeContext';
import { fmtDateTime, fmtValue, humanize } from '../lib/format';
import { useToast } from '../lib/toastContext';

const MAX = 8;

export function ComparePage() {
  const [sp, setSp] = useSearchParams();
  const { landscapeId } = useLandscape();
  const { notify } = useToast();
  const ids = useMemo(() => (sp.get('ids') ?? '').split(',').filter(Boolean), [sp]);
  const setIds = (next: string[]) => setSp(next.length ? { ids: next.join(',') } : {}, { replace: true });
  const members = useQuery({ queryKey: ['landscape', landscapeId], queryFn: () => api.landscape(landscapeId as string), enabled: Boolean(landscapeId) });
  const assets = (members.data?.members ?? []).filter((m) => m.entity_type === 'asset');
  const labels = new Map(assets.map((a) => [a.entity_id, a.label ?? a.entity_id]));
  const cmp = useQuery({ queryKey: ['compare', ids], queryFn: () => api.compare(ids), enabled: ids.length >= 2 });
  const add = (id: string) => {
    if (ids.includes(id)) return;
    if (ids.length >= MAX) {
      notify(`You can compare up to ${MAX} assets`, 'error');
      return;
    }
    setIds([...ids, id]);
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Compare assets</h1>
          <p>Side-by-side attributes with provenance. Comparisons across trials are indirect.</p>
        </div>
        {ids.length >= 2 ? <ExportButtons label="Export comparison" formats={['docx', 'pdf', 'pptx', 'md']} onExport={(f) => api.compareExport(ids, f)} /> : null}
      </div>
      <section className="card" aria-labelledby="sel-h" style={{ marginBottom: 16 }}>
        <h2 id="sel-h">Assets to compare ({ids.length}/{MAX})</h2>
        <div className="row" style={{ marginBottom: 10 }}>
          {ids.length === 0 ? <span className="small muted">Pick at least two assets.</span> : null}
          {ids.map((id) => (
            <span key={id} className="badge badge-info">
              {labels.get(id) ?? cmp.data?.rows.find((r) => r.asset_id === id)?.asset ?? id.slice(0, 8)}
              <button type="button" className="btn btn-ghost btn-sm" style={{ height: 18 }} aria-label={`Remove ${labels.get(id) ?? id}`} onClick={() => setIds(ids.filter((x) => x !== id))}>
                <X size={12} aria-hidden />
              </button>
            </span>
          ))}
        </div>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="cmp-add">Add from current landscape</label>
            <select
              id="cmp-add"
              value=""
              onChange={(e) => {
                if (e.target.value) add(e.target.value);
              }}
            >
              <option value="">Select an asset...</option>
              {assets
                .filter((a) => !ids.includes(a.entity_id))
                .map((a) => (
                  <option key={a.entity_id} value={a.entity_id}>
                    {a.label} {a.role === 'customer' ? '(your asset)' : ''}
                  </option>
                ))}
            </select>
          </div>
          <div style={{ gridColumn: 'span 2' }}>
            <EntityPicker label="Or search any asset" type="asset" onSelect={(h) => add(h.id)} />
          </div>
        </div>
      </section>
      {ids.length < 2 ? (
        <div className="card">
          <EmptyState title="Select two or more assets to compare" />
        </div>
      ) : (
        <QueryView query={cmp} loadingLabel="Building comparison">
          {(c) => (
            <div className="stack">
              <div className="banner banner-indirect" role="note" aria-label="Comparison warnings">
                <AlertTriangle size={20} aria-hidden />
                <div>
                  <p>
                    <strong>Indirect comparison - read before interpreting</strong>
                  </p>
                  <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                    {c.context_warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </div>
              </div>
              <div className="table-wrap">
                <table className="table">
                  <caption className="sr-only">Attribute comparison; values show provenance on hover or focus</caption>
                  <thead>
                    <tr>
                      <th scope="col">Attribute</th>
                      {c.rows.map((r) => (
                        <th key={r.asset_id} scope="col">
                          <Link to={`/assets/${r.asset_id}`}>{r.asset}</Link>
                          <div className="row" style={{ gap: 4 }}>
                            {r.role === 'customer' ? <span className="badge badge-danger">Your asset</span> : null}
                            {r.stale ? <StaleBadge /> : null}
                          </div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {c.columns.map((col) => (
                      <tr key={col}>
                        <th scope="row">{humanize(col)}</th>
                        {c.rows.map((r) => {
                          const cell = r.cells[col];
                          return (
                            <td key={r.asset_id}>
                              {cell && cell.value !== null && cell.value !== undefined && cell.value !== '' ? (
                                <ProvenanceCell provenance={cell.provenance}>{fmtValue(cell.value)}</ProvenanceCell>
                              ) : (
                                <span className="muted">Unknown</span>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="tiny muted">Generated {fmtDateTime(c.generated_at)}.</p>
            </div>
          )}
        </QueryView>
      )}
    </>
  );
}
