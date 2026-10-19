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
import { AddDrugButton, MonitoringEditor } from '../components/LandscapeSetup';
import { ProvenanceCell } from '../components/Provenance';
import { EmptyState, InlineError, QueryView } from '../components/States';
import { Tabs } from '../components/Tabs';
import { useLandscape } from '../state/landscapeContext';
import { fmtValue, humanize } from '../lib/format';
import { DIMENSION_LABELS, entityTypeLabel, roleLabel } from '../lib/labels';
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
          <strong>Indirect comparison:</strong> {matrix.note ?? 'Values come from different trials and are shown side by side for context only; they do not show that one drug is better.'}{' '}
          Hover over (or tab to) any value to see where it came from and when it was checked.
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
          <label htmlFor="mx-mech">How it works (mechanism)</label>
          <select id="mx-mech" value={mechanism} onChange={(e) => setMechanism(e.target.value)}>
            <option value="">All mechanisms</option>
            {mechanisms.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="mx-text">Search (disease, patients, endpoint...)</label>
          <input id="mx-text" type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. 1L, NSCLC, PFS" />
        </div>
        <p className="small muted" style={{ margin: 0 }}>
          Showing {rows.length} of {matrix.rows.length} drugs
        </p>
      </div>
      {rows.length === 0 ? (
        <EmptyState title="No drugs match these filters">Clear the company, mechanism or search filter to see all drugs.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <caption className="sr-only">Competitor comparison table; each value shows its source on hover or focus</caption>
            <thead>
              <tr>
                <th scope="col">Drug</th>
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
                      {r.role === 'customer' ? <span className="badge badge-danger">Your drug</span> : <span className="badge badge-neutral">{roleLabel(r.role)}</span>}
                      {r.stale ? <StaleBadge /> : null}
                    </div>
                  </th>
                  {matrix.columns.map((c) => {
                    const cell = r.cells[c];
                    if (!cell || cell.value === null || cell.value === undefined || cell.value === '') {
                      return (
                        <td key={c}>
                          <span className="muted" title="None of our sources report this value yet">
                            Not reported
                          </span>
                        </td>
                      );
                    }
                    return (
                      <td key={c} style={{ minWidth: 110, maxWidth: c === 'next_milestone' ? 260 : 200 }}>
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
      notify('Saved. New changes will be scored with these settings.');
      void qc.invalidateQueries({ queryKey: ['landscape', landscape.id] });
      void qc.invalidateQueries({ queryKey: ['landscapes'] });
    },
  });
  const addMember = useMutation({
    mutationFn: (m: { entity_type: string; entity_id: string }) => api.addMembers(landscape.id, [{ ...m, role }]),
    onSuccess: (r) => {
      notify(r.added ? 'Added to this market' : 'Already in this market');
      void qc.invalidateQueries({ queryKey: ['landscape', landscape.id] });
      void qc.invalidateQueries({ queryKey: ['matrix', landscape.id] });
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  const removeMember = useMutation({
    mutationFn: (entityId: string) => api.removeMember(landscape.id, entityId),
    onSuccess: () => {
      notify('Removed from this market');
      void qc.invalidateQueries({ queryKey: ['landscape', landscape.id] });
      void qc.invalidateQueries({ queryKey: ['matrix', landscape.id] });
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  const canConfig = can(PERMS.configAdmin);
  const canWrite = can(PERMS.landscapeWrite);
  return (
    <div className="grid grid-2">
      <MonitoringEditor landscape={landscape} />
      <section className="card" aria-labelledby="thr-h">
        <h2 id="thr-h">Priority thresholds and score weights</h2>
        <p className="small muted">
          Decide how high the importance score (0-100) must be for each priority level, and how much each factor counts. Changes take effect for newly detected items.
        </p>
        {!canConfig ? <p className="small muted">View only: ask an administrator to change these settings.</p> : null}
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            saveThresholds.mutate();
          }}
        >
          <fieldset disabled={!canConfig}>
            <legend>Minimum score for each priority level</legend>
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
            <legend>How much each factor counts (0-1)</legend>
            <div className="form-grid">
              {DIMENSIONS.map((d) => (
                <div className="field" key={d}>
                  <label htmlFor={`w-${d}`} title={DIMENSION_LABELS[d]?.description}>
                    {DIMENSION_LABELS[d]?.name ?? d}
                  </label>
                  <input id={`w-${d}`} type="number" min={0} max={1} step={0.05} value={weights[d]} onChange={(e) => setWeights({ ...weights, [d]: e.target.value })} />
                </div>
              ))}
            </div>
          </fieldset>
          {canConfig ? (
            <>
              <div className="field">
                <label htmlFor="thr-reason">Reason for the change (kept in the activity log)</label>
                <input id="thr-reason" type="text" value={reason} onChange={(e) => setReason(e.target.value)} />
              </div>
              <InlineError error={saveThresholds.error} />
              <div>
                <button type="submit" className="btn btn-primary" disabled={saveThresholds.isPending}>
                  Save settings
                </button>
              </div>
            </>
          ) : null}
        </form>
      </section>
      <section className="card" aria-labelledby="mem-h">
        <div className="row-between">
          <h2 id="mem-h">What&rsquo;s in this market ({landscape.members.length})</h2>
          <AddDrugButton landscapeId={landscape.id} className="btn btn-sm" />
        </div>
        <p className="small muted">The drugs, companies and trials monitored here. Mark your own drugs as &ldquo;Your drug&rdquo; so changes are scored against them.</p>
        {canWrite ? (
          <div className="form-grid" style={{ marginBottom: 12 }}>
            <div className="field">
              <label htmlFor="mem-role">Add as</label>
              <select id="mem-role" value={role} onChange={(e) => setRole(e.target.value as typeof role)}>
                <option value="competitor">Competitor</option>
                <option value="customer">Your drug</option>
                <option value="monitored">Monitored (context only)</option>
              </select>
            </div>
            <div style={{ gridColumn: 'span 2' }}>
              <EntityPicker
                label="Add a drug, company or trial"
                onSelect={(h) => {
                  if (!['asset', 'company', 'trial'].includes(h.type)) {
                    notify('Only drugs, companies and trials can be added to a market', 'error');
                    return;
                  }
                  addMember.mutate({ entity_type: h.type, entity_id: h.id });
                }}
              />
            </div>
          </div>
        ) : null}
        {landscape.members.length === 0 ? <EmptyState title="Nothing monitored yet">Use the search above to add your drug, its competitors and their trials.</EmptyState> : null}
        <ul className="list-plain" style={{ maxHeight: 460, overflowY: 'auto' }}>
          {landscape.members.map((m) => (
            <li key={m.id} className="row-between">
              <span>
                {m.entity_type === 'asset' ? <Link to={`/assets/${m.entity_id}`}>{m.label ?? m.entity_id}</Link> : (m.label ?? m.entity_id)}{' '}
                <span className="badge badge-neutral">{entityTypeLabel(m.entity_type)}</span>{' '}
                <span className={`badge ${m.role === 'customer' ? 'badge-danger' : 'badge-neutral'}`}>{roleLabel(m.role)}</span>
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
      title="Create a new market (landscape)"
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
          <label htmlFor="cl-tpl">Start from a template</label>
          <select id="cl-tpl" value={form.template_id} onChange={(e) => setForm({ ...form, template_id: e.target.value })}>
            <option value="">No template (start blank)</option>
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
          <label htmlFor="cl-disease">Disease area</label>
          <input id="cl-disease" type="text" value={form.disease} onChange={(e) => setForm({ ...form, disease: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="cl-geo">Countries or regions (comma separated)</label>
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
          <p className="eyebrow">Competitor landscape</p>
          <h1>{detail.data?.name ?? 'Competitor landscape'}</h1>
          <p>
            {detail.data?.description ? `${detail.data.description} ` : ''}See who is developing what in this market: compare drugs side by side, explore how drugs, companies
            and trials are connected, or adjust what is monitored.
          </p>
        </div>
        <div className="btn-group">
          {landscapeId ? (
            <button type="button" className="btn" onClick={exportJson} title="Download all data for this market as a JSON file (for analysts and IT)">
              <Download size={15} aria-hidden /> Download data
            </button>
          ) : null}
          {can(PERMS.landscapeWrite) ? (
            <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
              <Plus size={15} aria-hidden /> New market
            </button>
          ) : null}
        </div>
      </div>
      {!loading && landscapes.length === 0 ? (
        <div className="card">
          <EmptyState title="No markets set up yet">Click &ldquo;New market&rdquo; and start from a template (for example a disease area) to begin monitoring competitors.</EmptyState>
        </div>
      ) : (
        <>
          <Tabs
            label="Landscape views"
            active={view}
            onChange={(v) => setSp(v === 'matrix' ? {} : { view: v }, { replace: true })}
            tabs={[
              { id: 'matrix', label: 'Comparison table' },
              { id: 'graph', label: 'Relationship map' },
              { id: 'config', label: 'Setup & thresholds' },
            ]}
          />
          <p className="small muted tab-intro">
            {view === 'matrix'
              ? 'Each row is a drug in this market; columns show key facts from trial registries and profiles. Your drug is highlighted.'
              : view === 'graph'
                ? 'How drugs, companies, trials and diseases are connected. Click a drug to open its profile.'
                : 'Choose what is monitored in this market and how changes are prioritised.'}
          </p>
          <div role="tabpanel" id={`panel-${view}`} aria-labelledby={`tab-${view}`}>
            {view === 'matrix' ? (
              <QueryView
                query={matrix}
                isEmpty={(m) => m.rows.length === 0}
                empty={<EmptyState title="No drugs in this market yet">Open &ldquo;Setup &amp; thresholds&rdquo; and add your drug and its competitors.</EmptyState>}
              >
                {(m) => <MatrixView matrix={m} />}
              </QueryView>
            ) : null}
            {view === 'graph' ? (
              <QueryView
                query={graph}
                isEmpty={(g) => g.nodes.length === 0}
                empty={<EmptyState title="No connections to show yet">Connections between drugs, companies and trials appear once sources have been checked.</EmptyState>}
              >
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
