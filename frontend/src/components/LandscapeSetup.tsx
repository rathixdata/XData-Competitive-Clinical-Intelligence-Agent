import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, RefreshCw, Trash2 } from 'lucide-react';
import { api } from '../api/endpoints';
import { ApiError } from '../api/client';
import type { LandscapeDetail } from '../api/types';
import { PERMS, useAuth } from '../auth/context';
import { Modal } from './Dialog';
import { InlineError } from './States';
import { errorMessage, useToast } from '../lib/toastContext';

const STAGES = ['Preclinical', 'Phase 1', 'Phase 2', 'Phase 3', 'Filed', 'Approved'];
const MODALITIES = ['Small molecule', 'Monoclonal antibody', 'Antibody-drug conjugate', 'Bispecific antibody', 'Cell therapy', 'Gene therapy', 'Vaccine', 'Other'];
// Connectors that read the searches edited below.
const SEARCH_CONNECTORS = ['ctgov', 'pubmed', 'openfda_label', 'openfda_drugsfda'];

const list = (s: string): string[] =>
  s
    .split(/[,\n]/)
    .map((x) => x.trim())
    .filter(Boolean);

const strings = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);

/** "Add your drug": creates one of the customer's own assets and adds it to the current market as "Your drug". */
export function AddDrugButton({ landscapeId, className = 'btn' }: { landscapeId?: string | null; className?: string }) {
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  if (!can(PERMS.landscapeWrite)) return null;
  return (
    <>
      <button type="button" className={className} onClick={() => setOpen(true)} title="Add one of your own drugs so competitor changes are scored against it">
        <Plus size={16} aria-hidden /> Add your drug
      </button>
      {open ? <AddDrugDialog landscapeId={landscapeId} onClose={() => setOpen(false)} /> : null}
    </>
  );
}

function AddDrugDialog({ landscapeId, onClose }: { landscapeId?: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { notify } = useToast();
  const [f, setF] = useState({
    name: '', aliases: '', stage: 'Phase 2', modality: 'Small molecule', mechanism: '', targets: '', indications: '',
    line_of_therapy: '', biomarkers: '', endpoint: '', route: '',
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const m = useMutation({
    mutationFn: async () => {
      const asset = await api.createAsset({
        name: f.name.trim(),
        aliases: list(f.aliases),
        stage: f.stage || null,
        modality: f.modality || null,
        profile: {
          mechanism: f.mechanism.trim(),
          targets: list(f.targets),
          modality: f.modality,
          indications: list(f.indications),
          line_of_therapy: f.line_of_therapy.trim(),
          biomarkers: list(f.biomarkers),
          endpoint: f.endpoint.trim(),
          route: f.route.trim(),
          stage: f.stage,
          population: [f.line_of_therapy.trim(), ...list(f.biomarkers)].filter(Boolean).join(' '),
        },
      });
      if (landscapeId) await api.addMembers(landscapeId, [{ entity_type: 'asset', entity_id: asset.id, role: 'customer' }]);
      return asset;
    },
    onSuccess: (asset) => {
      notify(`${asset.canonical_name} added. New competitor changes will be scored against it.`);
      void qc.invalidateQueries();
      onClose();
      navigate(`/assets/${asset.id}`);
    },
  });
  const valid = f.name.trim() && f.mechanism.trim() && list(f.indications).length > 0;
  return (
    <Modal
      open
      wide
      onClose={onClose}
      title="Add your drug"
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="add-drug" className="btn btn-primary" disabled={!valid || m.isPending}>
            {m.isPending ? 'Adding...' : 'Add drug'}
          </button>
        </>
      }
    >
      <form
        id="add-drug"
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) m.mutate();
        }}
      >
        <p className="small muted">
          The system compares every competitor change with this profile: the more a competitor shares (target, disease, line of therapy, biomarker,
          type of drug), the higher the change scores for you. This stays private to your organisation. You can edit it later on the drug&rsquo;s page.
        </p>
        <InlineError error={m.error} />
        <div className="form-grid">
          <div className="field">
            <label htmlFor="ad-name">Drug name or code (required)</label>
            <input id="ad-name" type="text" required maxLength={200} value={f.name} onChange={set('name')} placeholder="e.g. XD-202" data-autofocus />
          </div>
          <div className="field">
            <label htmlFor="ad-aliases">Other names (comma separated)</label>
            <input id="ad-aliases" type="text" value={f.aliases} onChange={set('aliases')} placeholder="e.g. XD202, generic name" />
          </div>
          <div className="field">
            <label htmlFor="ad-stage">Development stage</label>
            <select id="ad-stage" value={f.stage} onChange={set('stage')}>
              {STAGES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="ad-modality">Type of drug</label>
            <select id="ad-modality" value={f.modality} onChange={set('modality')}>
              {MODALITIES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="ad-mech">How it works (mechanism, required)</label>
            <input id="ad-mech" type="text" value={f.mechanism} onChange={set('mechanism')} placeholder="e.g. EGFR inhibitor" />
          </div>
          <div className="field">
            <label htmlFor="ad-targets">Biological targets (comma separated)</label>
            <input id="ad-targets" type="text" value={f.targets} onChange={set('targets')} placeholder="e.g. EGFR" />
          </div>
          <div className="field">
            <label htmlFor="ad-ind">Diseases (comma separated, required)</label>
            <input id="ad-ind" type="text" value={f.indications} onChange={set('indications')} placeholder="e.g. Non-small cell lung cancer" />
          </div>
          <div className="field">
            <label htmlFor="ad-line">Line of therapy</label>
            <input id="ad-line" type="text" value={f.line_of_therapy} onChange={set('line_of_therapy')} placeholder="e.g. 1L, 2L+" />
          </div>
          <div className="field">
            <label htmlFor="ad-bm">Biomarkers (comma separated)</label>
            <input id="ad-bm" type="text" value={f.biomarkers} onChange={set('biomarkers')} placeholder="e.g. EGFR exon 20 insertion" />
          </div>
          <div className="field">
            <label htmlFor="ad-ep">Primary endpoint of your main trial</label>
            <input id="ad-ep" type="text" value={f.endpoint} onChange={set('endpoint')} placeholder="e.g. Objective response rate" />
          </div>
          <div className="field">
            <label htmlFor="ad-route">How it is given</label>
            <input id="ad-route" type="text" value={f.route} onChange={set('route')} placeholder="e.g. Oral, once daily" />
          </div>
        </div>
        {!landscapeId ? <p className="small muted">No market is selected, so the drug is not added to one yet. Add it on the Competitor landscape page.</p> : null}
      </form>
    </Modal>
  );
}

interface TrialSearch {
  cond: string;
  intr: string;
}

/** Editor for what a market (landscape) monitors in the live sources, plus an on-demand check. */
export function MonitoringEditor({ landscape }: { landscape: LandscapeDetail }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const { notify } = useToast();
  const cfg = landscape.config ?? {};
  const [trials, setTrials] = useState<TrialSearch[]>(() => {
    const t = Array.isArray(cfg.trial_queries) ? (cfg.trial_queries as Record<string, string>[]) : [];
    return t.length ? t.map((q) => ({ cond: q.cond ?? '', intr: q.intr ?? '' })) : [{ cond: '', intr: '' }];
  });
  const [pubmed, setPubmed] = useState(() => strings(cfg.pubmed_queries).join('\n'));
  const [fda, setFda] = useState(() => strings(cfg.fda_products).join(', '));
  const [ncts, setNcts] = useState(() => strings(cfg.nct_ids).join(', '));
  const canWrite = can(PERMS.landscapeWrite);
  const canRun = can(PERMS.connectorAdmin);

  const save = useMutation({
    mutationFn: () =>
      api.patchLandscape(landscape.id, {
        config: {
          trial_queries: trials.filter((t) => t.cond.trim() || t.intr.trim()).map((t) => ({ ...(t.cond.trim() ? { cond: t.cond.trim() } : {}), ...(t.intr.trim() ? { intr: t.intr.trim() } : {}) })),
          pubmed_queries: pubmed
            .split('\n')
            .map((x) => x.trim())
            .filter(Boolean),
          fda_products: list(fda),
          nct_ids: list(ncts).map((x) => x.toUpperCase()),
        },
        reason: 'Updated monitored searches',
      }),
    onSuccess: () => {
      notify(canRun ? 'Saved. Use "Check sources now" to fetch matching records right away.' : 'Saved. Matching records are fetched on the next scheduled check.');
      void qc.invalidateQueries({ queryKey: ['landscape', landscape.id] });
    },
  });
  const run = useMutation({
    mutationFn: async () => {
      // A source that is already being checked answers "in progress"; that is fine, so only fail if none started.
      const results = await Promise.allSettled(SEARCH_CONNECTORS.map((key) => api.runConnector(key)));
      const started = results.filter((r) => r.status === 'fulfilled').length;
      const busy = results.filter((r) => r.status === 'rejected' && r.reason instanceof ApiError && r.reason.status === 409).length;
      if (started + busy === 0) throw (results.find((r) => r.status === 'rejected') as PromiseRejectedResult).reason;
    },
    onSuccess: () => notify('Checking ClinicalTrials.gov, PubMed and FDA now. New changes appear in All changes within a few minutes.'),
    onError: (e) => notify(errorMessage(e), 'error'),
  });

  return (
    <section className="card" aria-labelledby="mon-h" style={{ gridColumn: '1 / -1' }}>
      <div className="row-between">
        <h2 id="mon-h">What this market monitors</h2>
        {canRun ? (
          <button type="button" className="btn" onClick={() => run.mutate()} disabled={run.isPending} title="Fetch the latest records for these searches now instead of waiting for the schedule">
            <RefreshCw size={16} aria-hidden /> {run.isPending ? 'Starting...' : 'Check sources now'}
          </button>
        ) : null}
      </div>
      <p className="small muted">
        These searches decide which live records are collected. Every time a matching record changes (a trial&rsquo;s enrollment, dates, endpoints or status, a new
        publication, an FDA label update), the change is scored against your drugs. Sources are checked automatically several times a day.
      </p>
      {!canWrite ? <p className="small muted">View only: ask an administrator to change these searches.</p> : null}
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <fieldset disabled={!canWrite}>
          <legend>ClinicalTrials.gov searches</legend>
          <p className="hint">A disease and, optionally, a drug or drug class. Example: &ldquo;non-small cell lung cancer&rdquo; + &ldquo;EGFR inhibitor&rdquo;.</p>
          <div className="stack-sm">
            {trials.map((t, i) => (
              <div key={i} className="form-grid">
                <div className="field">
                  <label htmlFor={`mq-cond-${i}`}>Disease</label>
                  <input id={`mq-cond-${i}`} type="text" value={t.cond} onChange={(e) => setTrials(trials.map((x, j) => (j === i ? { ...x, cond: e.target.value } : x)))} />
                </div>
                <div className="field">
                  <label htmlFor={`mq-intr-${i}`}>Drug or drug class (optional)</label>
                  <input id={`mq-intr-${i}`} type="text" value={t.intr} onChange={(e) => setTrials(trials.map((x, j) => (j === i ? { ...x, intr: e.target.value } : x)))} />
                </div>
                <div className="field" style={{ alignSelf: 'end' }}>
                  <button type="button" className="btn btn-ghost" onClick={() => setTrials(trials.length > 1 ? trials.filter((_, j) => j !== i) : [{ cond: '', intr: '' }])} aria-label={`Remove search ${i + 1}`}>
                    <Trash2 size={14} aria-hidden /> Remove
                  </button>
                </div>
              </div>
            ))}
            <div>
              <button type="button" className="btn btn-sm" onClick={() => setTrials([...trials, { cond: '', intr: '' }])}>
                <Plus size={14} aria-hidden /> Add a trial search
              </button>
            </div>
          </div>
        </fieldset>
        <fieldset disabled={!canWrite}>
          <legend>Specific trials to follow</legend>
          <div className="field">
            <label htmlFor="mq-nct">ClinicalTrials.gov IDs (comma separated)</label>
            <input id="mq-nct" type="text" value={ncts} onChange={(e) => setNcts(e.target.value)} placeholder="e.g. NCT04487080, NCT05048797" />
            <span className="hint">These trials are checked every time, even if they don&rsquo;t match a search.</span>
          </div>
        </fieldset>
        <fieldset disabled={!canWrite}>
          <legend>PubMed searches (one per line)</legend>
          <div className="field">
            <label htmlFor="mq-pubmed">PubMed search terms</label>
            <textarea id="mq-pubmed" rows={3} value={pubmed} onChange={(e) => setPubmed(e.target.value)} placeholder="e.g. non-small cell lung cancer[tiab] AND EGFR[tiab]" />
            <span className="hint">Uses PubMed&rsquo;s own search syntax; [tiab] means title or abstract.</span>
          </div>
        </fieldset>
        <fieldset disabled={!canWrite}>
          <legend>FDA products to follow</legend>
          <div className="field">
            <label htmlFor="mq-fda">Drug names (comma separated)</label>
            <input id="mq-fda" type="text" value={fda} onChange={(e) => setFda(e.target.value)} placeholder="e.g. osimertinib, amivantamab" />
            <span className="hint">Label changes and new approvals for these drugs are reported.</span>
          </div>
        </fieldset>
        {canWrite ? (
          <>
            <InlineError error={save.error} />
            <div>
              <button type="submit" className="btn btn-primary" disabled={save.isPending}>
                Save searches
              </button>
            </div>
          </>
        ) : null}
      </form>
    </section>
  );
}
