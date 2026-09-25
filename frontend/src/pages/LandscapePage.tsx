import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Download, Plus, Trash2 } from 'lucide-react';
import { api } from '../api/endpoints';
import { BANDS, type LandscapeDetail, type Matrix } from '../api/types';
import { saveBlob } from '../api/client';
import { PERMS, useAuth } from '../auth/context';
import { BandBadge, StaleBadge } from '../components/Badges';
import { Modal } from '../components/Dialog';
import { EntityPicker } from '../components/EntityPicker';
import { GraphView } from '../components/GraphView';
import { ProvenanceCell } from '../components/Provenance';
import { EmptyState, InlineError, QueryView } from '../components/States';
import { Tabs } from '../components/Tabs';
import { useLandscape } from '../state/landscapeContext';
import { fmtValue, humanize } from '../lib/format';
import { errorMessage, useToast } from '../lib/toastContext';

function cellText(v: unknown): string {
  return fmtValue(v);
}

function MatrixView({ matrix }: { matrix: Matrix }) {
  const [company, setCompany] = useState('');
  const [mechanism, setMechanism] = useState('');
  const [text, setText] = useState('');
  const companies = useMemo(() => Array.from(new Set(matrix.rows.map((r) => cellText(r.cells.company?.value)).filter((x) => x !== '-'))).sort(), [matrix]);
  const mechanisms = useMemo(() => Array.from(new Set(matrix.rows.map((r) => cellText(r.cells.mechanism?.value)).filter((x) => x !== '-'))).sort(), [matrix]);
  const rows = matrix.rows.filter((r) => {
    if (company && cellText(r.cells.company?.value) !== company) return false;
    if (mechanism && cellText(r.cells.mechanism?.value) !== mechanism) return false;
    if (text) {
      const hay = [r.asset, ...Object.values(r.cells).map((c) => cellText(c.value))].join(' ').toLowerCase();
      if (!hay.includes(text.toLowerCase())) return false;
    }
    return true;
  });
  return (
    <div className="stack">
      <div className="banner banner-indirect" role="note">
        <AlertTriangle size={18} aria-hidden />
        <p>
          <strong>Indirect comparison:</strong> {matrix.note ?? 'Cross-trial attributes are shown side by side for context only; they do not establish superiority.'}{' '}
          Hover or focus any value to see its source, snapshot and retrieval date.
        </p>
      </div>
      <div className="form-grid" role="search" aria-label="Matrix filters">
        <div className="field">
          <label htmlFor="mx-company">Company</label>
          <select id="mx-company" value={company} onChange={(e) => setCompany(e.target.value)}>
            <option value="">All companies</option>
            {companies.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="mx-mech">Mechanism</label>
          <select id="mx-mech" value={mechanism} onChange={(e) => setMechanism(e.target.value)}>
            <option value="">All mechanisms</option>
            {mechanisms.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="mx-text">Indication / population / text</label>
          <input id="mx-text" type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. 1L, NSCLC, PFS" />
        </div>
        <p className="small muted" style={{ margin: 0 }}>
          {rows.length} of {matrix.rows.length} assets
        </p>
      </div>
      {rows.length === 0 ? (
        <EmptyState title="No assets match these filters" />
      ) : (
        <div className="table-wrap">
          <table className="table">
            <caption className="sr-only">Landscape matrix; each value shows its provenance on hover or focus</caption>
            <thead>
              <tr>
                <th scope="col">Asset</th>
                {matrix.columns.map((c) => (
                  <th key={c} scope="col">
                    {humanize(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.asset_id}>
                  <th scope="row" style={{ minWidth: 140 }}>
                    <Link to={`/assets/${r.asset_id}`}>{r.asset}</Link>
                    <div className="row" style={{ gap: 4, marginTop: 2 }}>
                      {r.role === 'customer' ? <span className="badge badge-danger">Your asset</span> : <span className="badge badge-neutral">{r.role}</span>}
                      {r.stale ? <StaleBadge /> : null}
                    </div>
                  </th>
                  {matrix.columns.map((c) => {
                    const cell = r.cells[c];
                    if (!cell || cell.value === null || cell.value === undefined || cell.value === '') {
                      return (
                        <td key={c}>
                          <span className="muted" title="Not reported by any retained source">
                            Unknown
                          </span>
                        </td>
                      );
                    }
                    return (
                      <td key={c} style={{ minWidth: 110 }}>
                        <ProvenanceCell provenance={cell.provenance}>{cellText(cell.value)}</ProvenanceCell>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const DIMENSIONS = ['R', 'C', 'P', 'T', 'N'];
const DIM_LABEL: Record<string, string> = { R: 'Relevance', C: 'Change significance', P: 'Proximity', T: 'Timing', N: 'Novelty' };

function ConfigView({ landscape }: { landscape: LandscapeDetail }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const { notify } = useToast();
  const cfg = landscape.config ?? {};
  const [bands, setBands] = useState<Record<string, string>>(() =>
    Object.fromEntries(BANDS.filter((b) => b !== 'Archive').map((b) => [b, String(cfg.band_thresholds?.[b] ?? '')])),
  );
  const [weights, setWeights] = useState<Record<string, string>>(() => Object.fromEntries(DIMENSIONS.map((d) => [d, String(cfg.materiality_weights?.[d] ?? '')])));
  const [reason, setReason] = useState('');
  const [role, setRole] = useState<'competitor' | 'customer' | 'monitored'>('competitor');
  const saveThresholds = useMutation({
    mutationFn: () =>
      api.putThresholds(landscape.id, {
        band_thresholds: Object.fromEntries(Object.entries(bands).filter(([, v]) => v !== '').map(([k, v]) => [k, Number(v)])),
        materiality_weights: Object.fromEntries(Object.entries(weights).filter(([, v]) => v !== '').map(([k, v]) => [k, Number(v)])),
        reason: reason || undefined,
      }),
    onSuccess: () => {
      notify('Thresholds saved (new landscape version)');
      void qc.invalidateQueries({ queryKey: ['landscape', landscape.id] });
      void qc.invalidateQueries({ queryKey: ['landscapes'] });
    },
  });
  const addMember = useMutation({
    mutationFn: (m: { entity_type: string; entity_id: string }) => api.addMembers(landscape.id, [{ ...m, role }]),
    onSuccess: (r) => {
      notify(r.added ? 'Member added' : 'Already a member');
      void qc.invalidateQueries({ queryKey: ['landscape', landscape.id] });
      void qc.invalidateQueries({ queryKey: ['matrix', landscape.id] });
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  const removeMember = useMutation({
    mutationFn: (entityId: string) => api.removeMember(landscape.id, entityId),
    onSuccess: () => {
      notify('Member removed');
      void qc.invalidateQueries({ queryKey: ['landscape', landscape.id] });
      void qc.invalidateQueries({ queryKey: ['matrix', landscape.id] });
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  const canConfig = can(PERMS.configAdmin);
  const canWrite = can(PERMS.landscapeWrite);
  return (
    <div className="grid grid-2">
      <section className="card" aria-labelledby="thr-h">
        <h2 id="thr-h">Materiality bands and weights</h2>
        {!canConfig ? <p className="small muted">Read-only: changing thresholds requires the config:admin permission.</p> : null}
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            saveThresholds.mutate();
          }}
        >
          <fieldset disabled={!canConfig}>
            <legend>Band thresholds (minimum score)</legend>
            <div className="form-grid">
              {Object.keys(bands).map((b) => (
                <div className="field" key={b}>
                  <label htmlFor={`thr-${b}`}>
                    <BandBadge band={b} />
                  </label>
                  <input id={`thr-${b}`} type="number" min={0} max={100} value={bands[b]} onChange={(e) => setBands({ ...bands, [b]: e.target.value })} />
                </div>
              ))}
            </div>
          </fieldset>
          <fieldset disabled={!canConfig}>
            <legend>Dimension weights</legend>
            <div className="form-grid">
              {DIMENSIONS.map((d) => (
                <div className="field" key={d}>
                  <label htmlFor={`w-${d}`}>
                    {DIM_LABEL[d]} ({d})
                  </label>
                  <input id={`w-${d}`} type="number" min={0} max={1} step={0.05} value={weights[d]} onChange={(e) => setWeights({ ...weights, [d]: e.target.value })} />
                </div>
              ))}
            </div>
          </fieldset>
          {canConfig ? (
            <>
              <div className="field">
                <label htmlFor="thr-reason">Reason (audited)</label>
                <input id="thr-reason" type="text" value={reason} onChange={(e) => setReason(e.target.value)} />
              </div>
              <InlineError error={saveThresholds.error} />
              <div>
                <button type="submit" className="btn btn-primary" disabled={saveThresholds.isPending}>
                  Save configuration
                </button>
              </div>
            </>
          ) : null}
        </form>
      </section>
      <section className="card" aria-labelledby="mem-h">
        <h2 id="mem-h">Members ({landscape.members.length})</h2>
        {canWrite ? (
          <div className="form-grid" style={{ marginBottom: 12 }}>
            <div className="field">
              <label htmlFor="mem-role">Role for new member</label>
              <select id="mem-role" value={role} onChange={(e) => setRole(e.target.value as typeof role)}>
                <option value="competitor">Competitor</option>
                <option value="customer">Customer (your asset)</option>
                <option value="monitored">Monitored</option>
              </select>
            </div>
            <div style={{ gridColumn: 'span 2' }}>
              <EntityPicker
                label="Add asset, company or trial"
                onSelect={(h) => {
                  if (!['asset', 'company', 'trial'].includes(h.type)) {
                    notify('Only assets, companies and trials can be landscape members', 'error');
                    return;
                  }
                  addMember.mutate({ entity_type: h.type, entity_id: h.id });
                }}
              />
            </div>
          </div>
        ) : null}
        <ul className="list-plain" style={{ maxHeight: 460, overflowY: 'auto' }}>
          {landscape.members.map((m) => (
            <li key={m.id} className="row-between">
              <span>
                {m.entity_type === 'asset' ? <Link to={`/assets/${m.entity_id}`}>{m.label ?? m.entity_id}</Link> : (m.label ?? m.entity_id)}{' '}
                <span className="badge badge-neutral">{m.entity_type}</span> <span className={`badge ${m.role === 'customer' ? 'badge-danger' : 'badge-neutral'}`}>{m.role}</span>
              </span>
              {canWrite ? (
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => removeMember.mutate(m.entity_id)} aria-label={`Remove ${m.label ?? m.entity_id}`}>
                  <Trash2 size={14} aria-hidden />
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function CreateLandscape({ open, onClose }: { open: boolean; onClose: () => void }) {
  const templates = useQuery({ queryKey: ['templates'], queryFn: api.templates, enabled: open });
  const qc = useQueryClient();
  const { notify } = useToast();
  const { setLandscapeId } = useLandscape();
  const [form, setForm] = useState({ name: '', description: '', disease: '', template_id: '', geographies: '' });
  const m = useMutation({
    mutationFn: () => {
      const t = templates.data?.find((x) => x.id === form.template_id);
      return api.createLandscape({
        name: form.name.trim(),
        description: form.description || undefined,
        disease: form.disease || undefined,
        geographies: form.geographies ? form.geographies.split(',').map((s) => s.trim()).filter(Boolean) : [],
        template_id: form.template_id || null,
        config: t ? { ...t.config } : {},
      });
    },
    onSuccess: (ls) => {
      notify(`Landscape "${ls.name}" created`);
      void qc.invalidateQueries({ queryKey: ['landscapes'] });
      setLandscapeId(ls.id);
      onClose();
    },
  });
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create landscape"
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="create-ls" className="btn btn-primary" disabled={!form.name.trim() || m.isPending}>
            Create
          </button>
        </>
      }
    >
      <form
        id="create-ls"
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          m.mutate();
        }}
      >
        <InlineError error={m.error} />
        <div className="field">
          <label htmlFor="cl-tpl">Template</label>
          <select id="cl-tpl" value={form.template_id} onChange={(e) => setForm({ ...form, template_id: e.target.value })}>
            <option value="">No template (blank configuration)</option>
            {(templates.data ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
                {t.therapeutic_area ? ` - ${t.therapeutic_area}` : ''}
              </option>
            ))}
          </select>
          {form.template_id ? <span className="hint">{templates.data?.find((t) => t.id === form.template_id)?.description}</span> : null}
        </div>
        <div className="field">
          <label htmlFor="cl-name">Name</label>
          <input id="cl-name" type="text" required maxLength={200} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-autofocus />
        </div>
        <div className="field">
          <label htmlFor="cl-disease">Disease</label>
          <input id="cl-disease" type="text" value={form.disease} onChange={(e) => setForm({ ...form, disease: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="cl-geo">Geographies (comma separated)</label>
          <input id="cl-geo" type="text" value={form.geographies} onChange={(e) => setForm({ ...form, geographies: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="cl-desc">Description</label>
          <textarea id="cl-desc" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </div>
      </form>
    </Modal>
  );
}

export function LandscapePage() {
  const { landscapeId, landscapes, loading, landscape } = useLandscape();
  const { can } = useAuth();
  const navigate = useNavigate();
  const { notify } = useToast();
  const [sp, setSp] = useSearchParams();
  const view = sp.get('view') ?? 'matrix';
  const [creating, setCreating] = useState(false);
  const detail = useQuery({ queryKey: ['landscape', landscapeId], queryFn: () => api.landscape(landscapeId as string), enabled: Boolean(landscapeId) });
  const matrix = useQuery({ queryKey: ['matrix', landscapeId], queryFn: () => api.matrix(landscapeId as string), enabled: Boolean(landscapeId) && view === 'matrix' });
  const graph = useQuery({ queryKey: ['graph', landscapeId], queryFn: () => api.graph(landscapeId as string), enabled: Boolean(landscapeId) && view === 'graph' });

  const exportJson = async () => {
    try {
      const data = await api.exportLandscape(landscapeId as string);
      saveBlob(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }), `landscape-${(detail.data?.name ?? landscape?.name ?? landscapeId ?? 'export').replace(/[^a-z0-9-]+/gi, '_')}.json`);
      notify('Landscape exported');
    } catch (e) {
      notify(`Export failed: ${errorMessage(e)}`, 'error');
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{detail.data?.name ?? 'Landscape'}</h1>
          <p>{detail.data?.description ?? 'Competitive landscape matrix, knowledge graph and configuration.'}</p>
        </div>
        <div className="btn-group">
          {landscapeId ? (
            <button type="button" className="btn" onClick={exportJson}>
              <Download size={15} aria-hidden /> Export JSON
            </button>
          ) : null}
          {can(PERMS.landscapeWrite) ? (
            <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
              <Plus size={15} aria-hidden /> New landscape
            </button>
          ) : null}
        </div>
      </div>
      {!loading && landscapes.length === 0 ? (
        <div className="card">
          <EmptyState title="No landscapes yet">Create one from a template to start monitoring.</EmptyState>
        </div>
      ) : (
        <>
          <Tabs
            label="Landscape views"
            active={view}
            onChange={(v) => setSp(v === 'matrix' ? {} : { view: v }, { replace: true })}
            tabs={[
              { id: 'matrix', label: 'Matrix' },
              { id: 'graph', label: 'Graph' },
              { id: 'config', label: 'Configuration' },
            ]}
          />
          <div role="tabpanel" id={`panel-${view}`} aria-labelledby={`tab-${view}`}>
            {view === 'matrix' ? (
              <QueryView query={matrix} isEmpty={(m) => m.rows.length === 0} empty={<EmptyState title="No assets in this landscape" />}>
                {(m) => <MatrixView matrix={m} />}
              </QueryView>
            ) : null}
            {view === 'graph' ? (
              <QueryView query={graph} isEmpty={(g) => g.nodes.length === 0} empty={<EmptyState title="No graph relationships yet" />}>
                {(g) => <GraphView graph={g} onActivate={(n) => n.type === 'asset' && navigate(`/assets/${n.id}`)} />}
              </QueryView>
            ) : null}
            {view === 'config' ? <QueryView query={detail}>{(d) => <ConfigView key={`${d.id}-${d.version}`} landscape={d} />}</QueryView> : null}
          </div>
        </>
      )}
      {creating ? <CreateLandscape open={creating} onClose={() => setCreating(false)} /> : null}
    </>
  );
}
