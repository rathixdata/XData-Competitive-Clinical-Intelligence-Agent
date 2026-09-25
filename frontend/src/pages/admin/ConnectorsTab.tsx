import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { History, Play } from 'lucide-react';
import { api } from '../../api/endpoints';
import type { ConnectorHealth } from '../../api/types';
import { PERMS, useAuth } from '../../auth/context';
import { StaleBadge, StatusBadge } from '../../components/Badges';
import { Drawer } from '../../components/Dialog';
import { EmptyState, QueryView } from '../../components/States';
import { fmtDateTime, fmtRelative } from '../../lib/format';
import { errorMessage, useToast } from '../../lib/toastContext';

function Runs({ connector, onClose }: { connector: ConnectorHealth | null; onClose: () => void }) {
  const q = useQuery({ queryKey: ['connector-runs', connector?.key], queryFn: () => api.connectorRuns(connector?.key as string), enabled: Boolean(connector) });
  return (
    <Drawer open={Boolean(connector)} onClose={onClose} title={`Run history: ${connector?.display_name ?? ''}`}>
      <QueryView query={q} isEmpty={(d) => d.items.length === 0} empty={<EmptyState title="No runs recorded" />}>
        {(d) => (
          <ol className="list-plain">
            {d.items.map((r) => (
              <li key={r.id} className="stack-sm">
                <div className="row">
                  <StatusBadge status={r.status} />
                  <strong>{fmtDateTime(r.started_at)}</strong>
                  <span className="badge badge-neutral">{r.trigger}</span>
                </div>
                <span className="small">
                  Fetched {r.records_fetched}, new {r.records_new}, changed {r.records_changed}, unchanged {r.records_unchanged ?? '-'}; {r.changes_emitted} changes emitted;{' '}
                  {r.errors} errors.
                </span>
                {r.finished_at ? <span className="tiny muted">Finished {fmtDateTime(r.finished_at)}</span> : <span className="tiny muted">Still running</span>}
                {r.message ? <span className="small">{r.message}</span> : null}
              </li>
            ))}
          </ol>
        )}
      </QueryView>
    </Drawer>
  );
}

export function ConnectorsTab() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const { notify } = useToast();
  const q = useQuery({ queryKey: ['connectors'], queryFn: api.connectors, refetchInterval: 30_000 });
  const [runs, setRuns] = useState<ConnectorHealth | null>(null);
  const run = useMutation({
    mutationFn: (key: string) => api.runConnector(key),
    onSuccess: (_r, key) => {
      notify(`Run queued for ${key}; progress appears in run history`);
      void qc.invalidateQueries({ queryKey: ['connectors'] });
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  return (
    <>
      <QueryView query={q} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No connectors configured" />}>
        {(list) => (
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Source connectors and freshness</caption>
              <thead>
                <tr>
                  <th scope="col">Connector</th>
                  <th scope="col">State</th>
                  <th scope="col">Last success</th>
                  <th scope="col">Freshness (target)</th>
                  <th scope="col">Next run</th>
                  <th scope="col">Last run records</th>
                  <th scope="col" className="num">
                    Failures (7d)
                  </th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {list.map((c) => (
                  <tr key={c.key}>
                    <td>
                      <strong>{c.display_name}</strong>
                      <div className="tiny muted mono">
                        {c.key} v{c.adapter_version} - {c.schedule_cron}
                      </div>
                    </td>
                    <td>
                      <div className="row" style={{ gap: 4 }}>
                        <StatusBadge status={c.state} />
                        {c.stale ? <StaleBadge /> : null}
                        {!c.enabled && c.state !== 'disabled' ? <span className="badge badge-neutral">disabled</span> : null}
                      </div>
                    </td>
                    <td className="nowrap">{c.last_success_at ? fmtRelative(c.last_success_at) : 'Never'}</td>
                    <td className="nowrap">
                      {c.hours_since_success !== null ? `${c.hours_since_success.toFixed(1)} h` : '-'} / {c.freshness_slo_hours} h
                    </td>
                    <td className="nowrap">{fmtDateTime(c.next_run_at)}</td>
                    <td className="small">
                      {c.last_run
                        ? `${c.last_run.records_fetched} fetched, ${c.last_run.records_changed} changed, ${c.last_run.changes_emitted} changes (${c.last_run.status})`
                        : '-'}
                    </td>
                    <td className="num">{c.failures_last_7d}</td>
                    <td>
                      <div className="btn-group">
                        {can(PERMS.connectorAdmin) ? (
                          <button
                            type="button"
                            className="btn btn-sm"
                            disabled={!c.enabled || run.isPending}
                            onClick={() => run.mutate(c.key)}
                            aria-label={`Run ${c.display_name} now`}
                          >
                            <Play size={13} aria-hidden /> Run now
                          </button>
                        ) : null}
                        <button type="button" className="btn btn-sm" onClick={() => setRuns(c)} aria-label={`Run history for ${c.display_name}`}>
                          <History size={13} aria-hidden /> History
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </QueryView>
      <Runs connector={runs} onClose={() => setRuns(null)} />
    </>
  );
}
