import { useState, type FormEvent } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { ShieldAlert, ShieldCheck } from 'lucide-react';
import { api } from '../../api/endpoints';
import { PERMS, useAuth } from '../../auth/context';
import { ExportButtons } from '../../components/ExportButtons';
import { EmptyState, QueryView } from '../../components/States';
import { fmtDateTime, shortId } from '../../lib/format';

interface AuditFilter {
  action: string;
  resource_type: string;
  resource_id: string;
  actor_id: string;
  since: string;
  until: string;
}

const EMPTY: AuditFilter = { action: '', resource_type: '', resource_id: '', actor_id: '', since: '', until: '' };

function toQuery(f: AuditFilter) {
  return {
    action: f.action || undefined,
    resource_type: f.resource_type || undefined,
    resource_id: f.resource_id || undefined,
    actor_id: f.actor_id || undefined,
    since: f.since || undefined,
    until: f.until ? `${f.until}T23:59:59` : undefined,
  };
}

export function AuditTab() {
  const { can } = useAuth();
  const [draft, setDraft] = useState<AuditFilter>(EMPTY);
  const [filter, setFilter] = useState<AuditFilter>(EMPTY);
  const [offset, setOffset] = useState(0);
  const query = toQuery(filter);
  const q = useQuery({ queryKey: ['audit', query, offset], queryFn: () => api.audit({ ...query, offset, limit: 50 }), placeholderData: keepPreviousData });
  const verify = useQuery({ queryKey: ['audit-verify'], queryFn: api.auditVerify });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setOffset(0);
    setFilter(draft);
  };
  return (
    <div className="stack" style={{ gap: 16 }}>
      <section className="card" aria-labelledby="chain-h">
        <div className="row-between">
          <h2 id="chain-h" style={{ margin: 0 }}>
            Hash-chain integrity
          </h2>
          <button type="button" className="btn btn-sm" onClick={() => void verify.refetch()} disabled={verify.isFetching}>
            Re-verify
          </button>
        </div>
        {verify.data ? (
          verify.data.valid ? (
            <p className="row" style={{ marginTop: 8 }} role="status">
              <span className="badge badge-success">
                <ShieldCheck size={12} aria-hidden /> Chain valid
              </span>
              {verify.data.checked} entries verified.
            </p>
          ) : (
            <p className="row" style={{ marginTop: 8 }} role="alert">
              <span className="badge badge-danger">
                <ShieldAlert size={12} aria-hidden /> Chain broken
              </span>
              First broken entry: #{String(verify.data.broken_at ?? '?')} ({verify.data.checked} checked).
            </p>
          )
        ) : verify.error ? (
          <p className="small" role="alert">
            Verification failed: {(verify.error as Error).message}
          </p>
        ) : (
          <p className="small muted">Verifying...</p>
        )}
      </section>
      <form className="card stack" onSubmit={submit} aria-label="Audit search">
        <div className="form-grid">
          <div className="field">
            <label htmlFor="au-action">Action (prefix)</label>
            <input id="au-action" type="text" placeholder="e.g. narrative." value={draft.action} onChange={(e) => setDraft({ ...draft, action: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="au-rt">Resource type</label>
            <input id="au-rt" type="text" placeholder="e.g. intel_event" value={draft.resource_type} onChange={(e) => setDraft({ ...draft, resource_type: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="au-rid">Resource id</label>
            <input id="au-rid" type="text" value={draft.resource_id} onChange={(e) => setDraft({ ...draft, resource_id: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="au-actor">Actor id</label>
            <input id="au-actor" type="text" value={draft.actor_id} onChange={(e) => setDraft({ ...draft, actor_id: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="au-since">Since</label>
            <input id="au-since" type="date" value={draft.since} onChange={(e) => setDraft({ ...draft, since: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="au-until">Until</label>
            <input id="au-until" type="date" value={draft.until} onChange={(e) => setDraft({ ...draft, until: e.target.value })} />
          </div>
        </div>
        <div className="row-between">
          <div className="btn-group">
            <button type="submit" className="btn btn-primary">
              Search
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => {
                setDraft(EMPTY);
                setFilter(EMPTY);
                setOffset(0);
              }}
            >
              Clear
            </button>
          </div>
          {can(PERMS.auditExport) ? (
            <ExportButtons
              label="Export audit log"
              formats={['csv', 'json'] as ('csv' | 'json')[]}
              onExport={(f) => api.auditExport(f, { action: query.action, resource_type: query.resource_type, since: query.since, until: query.until })}
            />
          ) : null}
        </div>
      </form>
      <QueryView query={q} isEmpty={(d) => d.items.length === 0} empty={<div className="card"><EmptyState title="No audit entries match" /></div>}>
        {(d) => (
          <>
            <div className="table-wrap">
              <table className="table">
                <caption className="sr-only">Audit log entries</caption>
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">Time</th>
                    <th scope="col">Actor</th>
                    <th scope="col">Action</th>
                    <th scope="col">Resource</th>
                    <th scope="col">Reason</th>
                    <th scope="col">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((a) => (
                    <tr key={a.id}>
                      <td className="num">{a.id}</td>
                      <td className="nowrap">{fmtDateTime(a.created_at)}</td>
                      <td className="small">
                        {a.actor_type} {shortId(a.actor_id)}
                      </td>
                      <td className="mono small">{a.action}</td>
                      <td className="small">
                        {a.resource_type ?? '-'} {a.resource_id ? shortId(a.resource_id) : ''}
                      </td>
                      <td className="small">{a.reason ?? '-'}</td>
                      <td>
                        {a.before || a.after ? (
                          <details>
                            <summary className="small">Before / after</summary>
                            <pre className="mono tiny" style={{ maxWidth: 420, maxHeight: 240, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
                              {JSON.stringify({ before: a.before, after: a.after }, null, 1)}
                            </pre>
                          </details>
                        ) : (
                          <span className="muted small">-</span>
                        )}
                        <div className="tiny muted mono" title={a.hash}>
                          hash {a.hash.slice(0, 10)}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row-between">
              <span className="small muted">
                {d.offset + 1}-{d.offset + d.items.length} of {d.total}
              </span>
              <div className="btn-group">
                <button type="button" className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>
                  Previous
                </button>
                <button type="button" className="btn btn-sm" disabled={d.next_offset === null} onClick={() => setOffset(d.next_offset ?? 0)}>
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </QueryView>
    </div>
  );
}
