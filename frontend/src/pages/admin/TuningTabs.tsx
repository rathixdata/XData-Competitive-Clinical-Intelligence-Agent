import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/endpoints';
import { BANDS } from '../../api/types';
import { PERMS, useAuth } from '../../auth/context';
import { BandBadge, StatusBadge } from '../../components/Badges';
import { EmptyState, InlineError, QueryView } from '../../components/States';
import { useLandscape } from '../../state/landscapeContext';
import { fmtDateTime, humanize, pct } from '../../lib/format';
import { errorMessage, useToast } from '../../lib/toastContext';

function Metrics({ m }: { m: Record<string, number | null> | undefined }) {
  if (!m) return <span className="muted">-</span>;
  return (
    <dl className="kv small">
      {Object.entries(m).map(([k, v]) => (
        <div key={k} style={{ display: 'contents' }}>
          <dt>{humanize(k)}</dt>
          <dd>{v === null ? 'n/a' : k.includes('precision') || k.includes('recall') ? pct(v, 1) : v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function TuningTab() {
  const { landscapeId, landscape } = useLandscape();
  const { can } = useAuth();
  const qc = useQueryClient();
  const { notify } = useToast();
  const tuning = useQuery({ queryKey: ['tuning', landscapeId], queryFn: () => api.tuning(landscapeId as string), enabled: Boolean(landscapeId) });
  const datasets = useQuery({ queryKey: ['datasets'], queryFn: api.datasets });
  const releases = useQuery({ queryKey: ['releases'], queryFn: api.releases });
  const [dsName, setDsName] = useState('');
  const [relVersion, setRelVersion] = useState('');
  const [relDataset, setRelDataset] = useState('');
  const createDs = useMutation({
    mutationFn: () => api.createDataset({ name: dsName, landscape_id: landscapeId ?? null }),
    onSuccess: () => {
      notify('Dataset frozen');
      setDsName('');
      void qc.invalidateQueries({ queryKey: ['datasets'] });
    },
  });
  const createRel = useMutation({
    mutationFn: () =>
      api.createRelease({ landscape_id: landscapeId as string, dataset_id: relDataset, version: relVersion, band_thresholds: tuning.data?.suggested ?? tuning.data?.current ?? {} }),
    onSuccess: () => {
      notify('Candidate release created and evaluated');
      setRelVersion('');
      void qc.invalidateQueries({ queryKey: ['releases'] });
    },
  });
  const promote = useMutation({
    mutationFn: (id: string) => api.promoteRelease(id),
    onSuccess: () => {
      notify('Release promoted; landscape thresholds updated');
      void qc.invalidateQueries({ queryKey: ['releases'] });
      void qc.invalidateQueries({ queryKey: ['tuning'] });
      void qc.invalidateQueries({ queryKey: ['landscapes'] });
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  return (
    <div className="stack" style={{ gap: 16 }}>
      <section className="card" aria-labelledby="ts-h">
        <h2 id="ts-h">Threshold suggestions for {landscape?.name ?? 'the selected landscape'}</h2>
        <p className="small muted">Suggestions come from analyst feedback labels (Material / Useful vs Not material / Not useful). Suggestions never apply automatically.</p>
        <QueryView query={tuning}>
          {(t) => (
            <div className="grid grid-2">
              <div>
                <h3>Current</h3>
                <ul className="list-plain">
                  {Object.entries(t.current).map(([b, v]) => (
                    <li key={b} className="row-between">
                      <BandBadge band={b} /> <span>&ge; {v}</span>
                    </li>
                  ))}
                </ul>
                <Metrics m={t.current_metrics} />
              </div>
              <div>
                <h3>Suggested</h3>
                {t.suggested ? (
                  <>
                    <ul className="list-plain">
                      {Object.entries(t.suggested).map(([b, v]) => (
                        <li key={b} className="row-between">
                          <BandBadge band={b} /> <span>&ge; {v}</span>
                        </li>
                      ))}
                    </ul>
                    <Metrics m={t.suggested_metrics as Record<string, number | null> | undefined} />
                  </>
                ) : (
                  <p className="small">No suggestion: {t.reason ?? 'insufficient data'}.</p>
                )}
              </div>
            </div>
          )}
        </QueryView>
      </section>
      <section className="card" aria-labelledby="ds-h">
        <h2 id="ds-h">Training datasets (frozen feedback snapshots)</h2>
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            createDs.mutate();
          }}
        >
          <div className="field">
            <label htmlFor="ds-name">Dataset name</label>
            <input id="ds-name" type="text" required maxLength={120} value={dsName} onChange={(e) => setDsName(e.target.value)} />
          </div>
          <div className="field">
            <button type="submit" className="btn" disabled={!dsName.trim() || createDs.isPending}>
              Freeze dataset
            </button>
          </div>
        </form>
        <InlineError error={createDs.error} />
        <QueryView query={datasets} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No datasets yet" />}>
          {(ds) => (
            <ul className="list-plain">
              {ds.map((d) => (
                <li key={d.id} className="row-between">
                  <span>
                    <strong>{d.name}</strong> v{d.version} - {d.record_count} records
                  </span>
                  <span className="tiny muted mono">
                    {d.content_hash.slice(0, 12)} - {fmtDateTime(d.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </QueryView>
      </section>
      <section className="card" aria-labelledby="rel-h">
        <h2 id="rel-h">Model releases (materiality thresholds)</h2>
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            createRel.mutate();
          }}
        >
          <div className="field">
            <label htmlFor="rel-ds">Evaluation dataset</label>
            <select id="rel-ds" required value={relDataset} onChange={(e) => setRelDataset(e.target.value)}>
              <option value="">Select...</option>
              {(datasets.data ?? []).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} v{d.version}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="rel-ver">Release version</label>
            <input id="rel-ver" type="text" required placeholder="e.g. thresholds-2026.10" value={relVersion} onChange={(e) => setRelVersion(e.target.value)} />
          </div>
          <div className="field">
            <button type="submit" className="btn" disabled={!relDataset || !relVersion.trim() || !landscapeId || createRel.isPending}>
              Create candidate from {tuning.data?.suggested ? 'suggestion' : 'current thresholds'}
            </button>
          </div>
        </form>
        <InlineError error={createRel.error} />
        <QueryView query={releases} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No releases yet" />}>
          {(rs) => (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Version</th>
                    <th scope="col">Status</th>
                    <th scope="col">Thresholds</th>
                    <th scope="col">Created</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {rs.map((r) => (
                    <tr key={r.id}>
                      <td>{r.version}</td>
                      <td>
                        <StatusBadge status={r.status} />
                      </td>
                      <td className="small">
                        {Object.entries(r.config.band_thresholds ?? {})
                          .map(([b, v]) => `${b} ${v}`)
                          .join(', ')}
                      </td>
                      <td className="nowrap small">{fmtDateTime(r.created_at)}</td>
                      <td>
                        {r.status === 'candidate' && can(PERMS.configAdmin) ? (
                          <button type="button" className="btn btn-sm" onClick={() => promote.mutate(r.id)} disabled={promote.isPending}>
                            Promote
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </QueryView>
      </section>
    </div>
  );
}

export function KpisTab() {
  const { landscapeId } = useLandscape();
  const [days, setDays] = useState(90);
  const q = useQuery({ queryKey: ['kpis', landscapeId, days], queryFn: () => api.kpis(landscapeId, days) });
  return (
    <div className="stack">
      <div className="field" style={{ maxWidth: 200 }}>
        <label htmlFor="kpi-days">Window</label>
        <select id="kpi-days" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[30, 90, 180, 365].map((d) => (
            <option key={d} value={d}>
              Last {d} days
            </option>
          ))}
        </select>
      </div>
      <QueryView query={q}>
        {(k) => {
          const tiles: { label: string; value: string; target?: string; ok?: boolean | null }[] = [
            {
              label: 'Source attribution rate (facts with evidence)',
              value: pct(k.source_attribution_rate, 1),
              target: pct(k.targets.source_attribution_rate),
              ok: k.source_attribution_rate === null ? null : k.source_attribution_rate >= k.targets.source_attribution_rate,
            },
            {
              label: 'High-priority precision',
              value: pct(k.high_priority_precision, 1),
              target: pct(k.targets.high_priority_precision),
              ok: k.high_priority_precision === null ? null : k.high_priority_precision >= k.targets.high_priority_precision,
            },
            {
              label: 'Useful alert rate',
              value: pct(k.useful_alert_rate, 1),
              target: pct(k.targets.useful_alert_rate),
              ok: k.useful_alert_rate === null ? null : k.useful_alert_rate >= k.targets.useful_alert_rate,
            },
            {
              label: 'Median fetch-to-publish (minutes)',
              value: k.median_fetch_to_publish_minutes === null ? '-' : String(k.median_fetch_to_publish_minutes),
              target: `<= ${k.targets.alert_latency_minutes}`,
              ok: k.median_fetch_to_publish_minutes === null ? null : k.median_fetch_to_publish_minutes <= k.targets.alert_latency_minutes,
            },
            { label: 'p95 fetch-to-publish (minutes)', value: k.p95_fetch_to_publish_minutes === null ? '-' : String(k.p95_fetch_to_publish_minutes) },
            { label: 'Events in window', value: String(k.events) },
            { label: 'Blocked publications', value: String(k.blocked_publications) },
            { label: 'Feedback records', value: String(k.feedback_count) },
          ];
          return (
            <div className="stack">
              <div className="grid grid-auto">
                {tiles.map((t) => (
                  <div key={t.label} className="card stat">
                    <span className="value">{t.value}</span>
                    <span className="label">{t.label}</span>
                    {t.target ? (
                      <span className="small">
                        Target {t.target}:{' '}
                        {t.ok === null || t.ok === undefined ? (
                          <span className="badge badge-neutral">Not enough data</span>
                        ) : t.ok ? (
                          <span className="badge badge-success">Meets target</span>
                        ) : (
                          <span className="badge badge-warning">Below target</span>
                        )}
                      </span>
                    ) : null}
                  </div>
                ))}
              </div>
              <section className="card" aria-labelledby="kb-h">
                <h2 id="kb-h">Events by band</h2>
                <ul className="row list-plain">
                  {BANDS.map((b) => (
                    <li key={b} style={{ border: 0, padding: 0 }}>
                      <BandBadge band={b} /> <strong>{k.by_band[b] ?? 0}</strong>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          );
        }}
      </QueryView>
    </div>
  );
}
