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
import { SOURCE_DESCRIPTIONS, humanizeEnum, sourceLabel } from '../../lib/labels';
import { errorMessage, useToast } from '../../lib/toastContext';

function Runs({ connector, onClose }: { connector: ConnectorHealth | null; onClose: () => void }) {
  const q = useQuery({ queryKey: ['connector-runs', connector?.key], queryFn: () => api.connectorRuns(connector?.key as string), enabled: Boolean(connector) });
  return (
    <Drawer open={Boolean(connector)} onClose={onClose} title={`Update history: ${connector ? sourceLabel(connector.key) : ''}`}>
      <QueryView query={q} isEmpty={(d) => d.items.length === 0} empty={<EmptyState title="This source has not been checked yet">Each scheduled or manual check will be listed here.</EmptyState>}>
        {(d) => (
          <ol className="list-plain">
            {d.items.map((r) => (
              <li key={r.id} className="stack-sm">
                <div className="row">
                  <StatusBadge status={r.status} />
                  <strong>{fmtDateTime(r.started_at)}</strong>
                  <span className="badge badge-neutral">{r.trigger === 'manual' ? 'Started by a user' : r.trigger === 'schedule' || r.trigger === 'scheduled' ? 'Scheduled' : humanizeEnum(r.trigger)}</span>
                </div>
                <span className="small">
                  Checked {r.records_fetched} records: {r.records_new} new, {r.records_changed} changed, {r.records_unchanged ?? '-'} unchanged. {r.changes_emitted} change(s)
                  detected; {r.errors} error(s).
                </span>
                {r.finished_at ? <span className="tiny muted">Finished {fmtDateTime(r.finished_at)}</span> : <span className="tiny muted">Still updating</span>}
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
      notify(`${sourceLabel(key)} will be checked now; see its update history for progress`);
      void qc.invalidateQueries({ queryKey: ['connectors'] });
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  return (
    <>
      <QueryView query={q} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No data sources set up">Ask your administrator to switch on the sources you need (for example ClinicalTrials.gov and PubMed).</EmptyState>}>
        {(list) => (
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Data sources and how up to date they are</caption>
              <thead>
                <tr>
                  <th scope="col">Data source</th>
                  <th scope="col" style={{ minWidth: 150 }}>
                    Status
                  </th>
                  <th scope="col">Last updated</th>
                  <th scope="col" title="Hours since the last successful update, compared with how often it should be updated">
                    Update target
                  </th>
                  <th scope="col">Last check</th>
                  <th scope="col" className="num" title="Failed updates in the last 7 days">
                    Failures (7d)
                  </th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {list.map((c) => (
                  <tr key={c.key}>
                    <td style={{ minWidth: 220 }}>
                      <strong title={SOURCE_DESCRIPTIONS[c.key]}>{sourceLabel(c.key) !== humanizeEnum(c.key) ? sourceLabel(c.key) : c.display_name}</strong>
                      {SOURCE_DESCRIPTIONS[c.key] ? <div className="tiny muted">{SOURCE_DESCRIPTIONS[c.key]}</div> : null}
                      <details className="tiny muted">
                        <summary>Technical details</summary>
                        <span className="mono">
                          {c.display_name} - {c.key} v{c.adapter_version} - schedule {c.schedule_cron}
                        </span>
                      </details>
                    </td>
                    <td>
                      <div className="row" style={{ gap: 4 }}>
                        <StatusBadge status={c.state} />
                        {c.stale ? <StaleBadge /> : null}
                        {!c.enabled && c.state !== 'disabled' ? <span className="badge badge-neutral">Turned off</span> : null}
                      </div>
                    </td>
                    <td>
                      <div className="nowrap">{c.last_success_at ? fmtRelative(c.last_success_at) : <span className="muted">Not yet</span>}</div>
                      <div className="tiny muted nowrap">Next check {fmtDateTime(c.next_run_at)}</div>
                    </td>
                    <td className="small">
                      every {c.freshness_slo_hours} h
                      {c.hours_since_success !== null ? <div className="tiny muted">last {c.hours_since_success.toFixed(1)} h ago</div> : null}
                    </td>
                    <td className="small">
                      {c.last_run
                        ? `${c.last_run.records_fetched} checked, ${c.last_run.changes_emitted} change(s)`
                        : 'Not checked yet'}
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
                            aria-label={`Check ${sourceLabel(c.key)} now`}
                            title="Check this source for changes right now"
                          >
                            <Play size={13} aria-hidden /> Check now
                          </button>
                        ) : null}
                        <button type="button" className="btn btn-sm" onClick={() => setRuns(c)} aria-label={`Update history for ${sourceLabel(c.key)}`} title="See past checks of this source">
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
