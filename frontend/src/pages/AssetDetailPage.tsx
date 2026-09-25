import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Columns3, PencilLine } from 'lucide-react';
import { api } from '../api/endpoints';
import type { Asset, ProfileField, ProfileVersion } from '../api/types';
import { PERMS, useAuth } from '../auth/context';
import { BandBadge, BasisBadge, ChangedDateBadge } from '../components/Badges';
import { Modal } from '../components/Dialog';
import { EmptyState, ErrorState, InlineError, Loading } from '../components/States';
import { catalystDate, previousDate } from '../lib/catalyst';
import { fmtDate, fmtDateTime, fmtValue, humanize, shortId } from '../lib/format';
import { useToast } from '../lib/toastContext';

function toInput(v: unknown, type: ProfileField['field_type']): string {
  if (v === null || v === undefined) return '';
  if (type === 'list' && Array.isArray(v)) return v.join('; ');
  return String(v);
}

function fromInput(s: string, type: ProfileField['field_type']): unknown {
  if (s.trim() === '') return type === 'list' ? [] : null;
  if (type === 'list') return s.split(/[;\n]/).map((x) => x.trim()).filter(Boolean);
  if (type === 'number') return Number(s);
  return s.trim();
}

function ProfileEditor({ asset, fields, onClose }: { asset: Asset; fields: ProfileField[]; onClose: () => void }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const keys = Array.from(new Set([...fields.map((f) => f.key), ...Object.keys(asset.profile ?? {})]));
  const defs = new Map(fields.map((f) => [f.key, f]));
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(keys.map((k) => [k, toInput(asset.profile?.[k], defs.get(k)?.field_type ?? (Array.isArray(asset.profile?.[k]) ? 'list' : 'text'))])),
  );
  const [reason, setReason] = useState('');
  const m = useMutation({
    mutationFn: () => {
      const profile: Record<string, unknown> = {};
      for (const k of keys) {
        const type = defs.get(k)?.field_type ?? (Array.isArray(asset.profile?.[k]) ? 'list' : 'text');
        profile[k] = fromInput(values[k] ?? '', type);
      }
      return api.patchProfile(asset.id, profile, reason);
    },
    onSuccess: () => {
      notify('Profile saved as a new version');
      void qc.invalidateQueries({ queryKey: ['asset', asset.id] });
      void qc.invalidateQueries({ queryKey: ['profile-versions', asset.id] });
      onClose();
    },
  });
  return (
    <Modal
      open
      onClose={onClose}
      wide
      title={`Edit profile: ${asset.canonical_name}`}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="profile-form" className="btn btn-primary" disabled={m.isPending}>
            Save new version
          </button>
        </>
      }
    >
      <form
        id="profile-form"
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          m.mutate();
        }}
      >
        <InlineError error={m.error} />
        <div className="grid grid-2">
          {keys.map((k) => {
            const def = defs.get(k);
            const type = def?.field_type ?? (Array.isArray(asset.profile?.[k]) ? 'list' : 'text');
            const id = `pf-${k}`;
            return (
              <div className="field" key={k}>
                <label htmlFor={id}>
                  {def?.label ?? humanize(k)}
                  {def?.required ? ' (required)' : ''}
                </label>
                {type === 'enum' && def ? (
                  <select id={id} required={def.required} value={values[k] ?? ''} onChange={(e) => setValues({ ...values, [k]: e.target.value })}>
                    <option value="">-</option>
                    {def.options.map((o) => (
                      <option key={o}>{o}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    id={id}
                    type={type === 'number' ? 'number' : type === 'date' ? 'date' : 'text'}
                    required={def?.required}
                    value={values[k] ?? ''}
                    onChange={(e) => setValues({ ...values, [k]: e.target.value })}
                  />
                )}
                {type === 'list' ? <span className="hint">Separate multiple values with semicolons</span> : null}
                {def?.description ? <span className="hint">{def.description}</span> : null}
              </div>
            );
          })}
        </div>
        <div className="field">
          <label htmlFor="pf-reason">Reason for change</label>
          <input id="pf-reason" type="text" value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
      </form>
    </Modal>
  );
}

function VersionList({ versions }: { versions: ProfileVersion[] }) {
  if (versions.length === 0) return <p className="small muted">No versions recorded.</p>;
  return (
    <ol className="list-plain">
      {versions.map((v, i) => {
        const prev = versions[i + 1];
        const changed = prev ? Object.keys({ ...v.profile, ...prev.profile }).filter((k) => JSON.stringify(v.profile[k]) !== JSON.stringify(prev.profile[k])) : [];
        return (
          <li key={v.id} className="stack-sm">
            <div className="row">
              <strong>Version {v.version}</strong>
              <span className="small muted">
                {fmtDateTime(v.changed_at)} by {shortId(v.changed_by)}
              </span>
            </div>
            {v.reason ? <span className="small">Reason: {v.reason}</span> : null}
            {changed.length ? (
              <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
                {changed.map((k) => (
                  <li key={k}>
                    {humanize(k)}: <span className="diff-old">{fmtValue(prev?.profile[k])}</span> to <span className="diff-new">{fmtValue(v.profile[k])}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

export function AssetDetailPage() {
  const { id = '' } = useParams();
  const { can } = useAuth();
  const [editing, setEditing] = useState(false);
  const q = useQuery({ queryKey: ['asset', id], queryFn: () => api.asset(id) });
  const versions = useQuery({ queryKey: ['profile-versions', id], queryFn: () => api.profileVersions(id) });
  const fields = useQuery({ queryKey: ['profile-fields'], queryFn: api.profileFields, staleTime: 10 * 60_000 });
  if (q.isLoading) return <Loading label="Loading asset" />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  if (!q.data) return null;
  const { asset, company, trials, publications, regulatory_events, catalysts, timeline } = q.data;
  const profile = asset.profile ?? {};
  const fieldDefs = fields.data ?? [];
  const orderedKeys = Array.from(new Set([...fieldDefs.map((f) => f.key), ...Object.keys(profile)])).filter((k) => k in profile);
  return (
    <>
      <div className="page-header">
        <div>
          <div className="row">
            {asset.is_internal ? <span className="badge badge-danger">Your asset (internal)</span> : <span className="badge badge-neutral">Competitor asset</span>}
            {asset.stage ? <span className="badge badge-neutral">{asset.stage}</span> : null}
            <span className="badge badge-neutral">Profile v{asset.profile_version}</span>
          </div>
          <h1 style={{ marginTop: 6 }}>{asset.canonical_name}</h1>
          <p>{[company?.canonical_name, asset.modality].filter(Boolean).join(' - ') || 'No company recorded'}</p>
        </div>
        <div className="btn-group">
          <Link className="btn" to={`/feed?asset_id=${asset.id}&asset_name=${encodeURIComponent(asset.canonical_name)}`}>
            Related events
          </Link>
          <Link className="btn" to={`/compare?ids=${asset.id}`}>
            <Columns3 size={15} aria-hidden /> Compare
          </Link>
          {can(PERMS.landscapeWrite) ? (
            <button type="button" className="btn btn-primary" onClick={() => setEditing(true)}>
              <PencilLine size={15} aria-hidden /> Edit profile
            </button>
          ) : null}
        </div>
      </div>
      <div className="grid grid-main-side">
        <div className="stack" style={{ gap: 16, minWidth: 0 }}>
          <section className="card" aria-labelledby="prof-h">
            <h2 id="prof-h">Profile</h2>
            {orderedKeys.length === 0 ? (
              <EmptyState title="No profile attributes" />
            ) : (
              <dl className="kv">
                {orderedKeys.map((k) => (
                  <div key={k} style={{ display: 'contents' }}>
                    <dt>{fieldDefs.find((f) => f.key === k)?.label ?? humanize(k)}</dt>
                    <dd>{fmtValue(profile[k])}</dd>
                  </div>
                ))}
              </dl>
            )}
            <p className="tiny muted" style={{ marginTop: 8 }}>
              {asset.is_internal ? 'Internal profile maintained by your team.' : 'Curated public profile; trial fields in the landscape matrix come from source snapshots.'}
            </p>
          </section>

          <section className="card" aria-labelledby="trials-h">
            <h2 id="trials-h">Trials ({trials.length})</h2>
            {trials.length === 0 ? (
              <EmptyState title="No linked trials" />
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Trial</th>
                      <th scope="col">Phase</th>
                      <th scope="col">Status</th>
                      <th scope="col" className="num">
                        Enrollment
                      </th>
                      <th scope="col">Primary completion</th>
                      <th scope="col">Primary endpoint(s)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trials.map((t) => (
                      <tr key={t.id}>
                        <td>
                          <a href={`https://clinicaltrials.gov/study/${t.nct_id}`} target="_blank" rel="noreferrer noopener">
                            {t.nct_id}
                            <span className="sr-only"> (opens ClinicalTrials.gov in a new tab)</span>
                          </a>
                          <div className="small">{t.title}</div>
                        </td>
                        <td>{t.phase ?? '-'}</td>
                        <td>{t.status ?? '-'}</td>
                        <td className="num">{fmtValue(t.enrollment)}</td>
                        <td>{fmtDate(t.primary_completion_date ?? null)}</td>
                        <td>{(t.primary_endpoints ?? []).filter(Boolean).join('; ') || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="card" aria-labelledby="tl-h">
            <h2 id="tl-h">Timeline</h2>
            {timeline.length === 0 ? (
              <EmptyState title="No timeline entries" />
            ) : (
              <ol className="list-plain">
                {timeline.map((t) => (
                  <li key={`${t.kind}-${t.id}`} className="row" style={{ alignItems: 'flex-start', flexWrap: 'nowrap' }}>
                    <span className="nowrap small strong" style={{ minWidth: 100 }}>
                      {fmtDate(t.date)}
                    </span>
                    <span className="badge badge-neutral">{t.kind}</span>
                    {t.band ? <BandBadge band={t.band} /> : null}
                    {t.kind === 'event' ? <Link to={`/events/${t.id}`}>{t.title}</Link> : <span>{t.title}</span>}
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
        <div className="stack" style={{ gap: 16, minWidth: 0 }}>
          <section className="card" aria-labelledby="cat-h">
            <h2 id="cat-h">Catalysts</h2>
            {catalysts.length === 0 ? (
              <p className="small muted">No catalysts.</p>
            ) : (
              <ul className="list-plain">
                {catalysts.map((c) => (
                  <li key={c.id} className="stack-sm">
                    <div className="row">
                      <strong>{catalystDate(c)}</strong>
                      <BasisBadge basis={c.date_basis} />
                      {c.history?.length ? <ChangedDateBadge previous={previousDate(c.history[c.history.length - 1])} /> : null}
                    </div>
                    <span className="small">{c.title}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="card" aria-labelledby="pub-h">
            <h2 id="pub-h">Publications ({publications.length})</h2>
            {publications.length === 0 ? (
              <p className="small muted">No linked publications.</p>
            ) : (
              <ul className="list-plain">
                {publications.map((p) => (
                  <li key={p.id} className="small">
                    {p.pmid ? (
                      <a href={`https://pubmed.ncbi.nlm.nih.gov/${p.pmid}/`} target="_blank" rel="noreferrer noopener">
                        {p.title}
                        <span className="sr-only"> (opens PubMed in a new tab)</span>
                      </a>
                    ) : (
                      p.title
                    )}
                    <div className="muted">
                      {p.journal ?? ''} {fmtDate(p.pub_date)}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="card" aria-labelledby="reg-h">
            <h2 id="reg-h">Regulatory events</h2>
            {regulatory_events.length === 0 ? (
              <p className="small muted">No regulatory events.</p>
            ) : (
              <ul className="list-plain">
                {regulatory_events.map((r) => (
                  <li key={r.id} className="small">
                    <strong>{fmtDate(r.event_date)}</strong> {humanize(r.event_type)} - {r.product_name}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="card" aria-labelledby="ver-h">
            <h2 id="ver-h">Profile versions</h2>
            {versions.isLoading ? <Loading /> : versions.error ? <ErrorState error={versions.error} /> : <VersionList versions={versions.data ?? []} />}
          </section>
        </div>
      </div>
      {editing ? <ProfileEditor asset={asset} fields={asset.is_internal ? fieldDefs : []} onClose={() => setEditing(false)} /> : null}
    </>
  );
}
