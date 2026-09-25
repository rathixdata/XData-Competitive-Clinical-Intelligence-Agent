import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FlaskConical, Plus, Power } from 'lucide-react';
import { api } from '../../api/endpoints';
import type { ProximityRule, ProximityTestPair } from '../../api/types';
import { StatusBadge } from '../../components/Badges';
import { Modal } from '../../components/Dialog';
import { EmptyState, InlineError, QueryView } from '../../components/States';
import { useLandscape } from '../../state/landscapeContext';
import { fmtDateTime, humanize } from '../../lib/format';
import { errorMessage, useToast } from '../../lib/toastContext';

const DIMS = ['target', 'modality', 'biomarker', 'geography', 'indication', 'line_of_therapy'];

function PairsTable({ pairs }: { pairs: ProximityTestPair[] }) {
  if (pairs.length === 0) return <p className="small muted">No asset pairs evaluated (the landscape may have no customer/competitor assets).</p>;
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">Proximity test results</caption>
        <thead>
          <tr>
            <th scope="col">Customer asset</th>
            <th scope="col">Competitor</th>
            <th scope="col" className="num">
              Score
            </th>
            <th scope="col">Mapped?</th>
            <th scope="col">Rationale</th>
          </tr>
        </thead>
        <tbody>
          {pairs.map((p, i) => (
            <tr key={i}>
              <td>{p.customer}</td>
              <td>{p.competitor}</td>
              <td className="num">{p.score.toFixed(2)}</td>
              <td>{p.mapped ? <span className="badge badge-success">Mapped</span> : <span className="badge badge-neutral">Below threshold</span>}</td>
              <td className="small">{p.rationale ?? '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CreateRule({ onClose }: { onClose: () => void }) {
  const { landscapes, landscapeId } = useLandscape();
  const qc = useQueryClient();
  const { notify } = useToast();
  const [name, setName] = useState('');
  const [ls, setLs] = useState(landscapeId ?? '');
  const [minP, setMinP] = useState('0.35');
  const [weights, setWeights] = useState<Record<string, string>>({ target: '0.3', modality: '0.1', biomarker: '0.15', geography: '0.05', indication: '0.25', line_of_therapy: '0.15' });
  const m = useMutation({
    mutationFn: () =>
      api.createProximityRule({
        name,
        landscape_id: ls || null,
        min_proximity: Number(minP),
        weights: Object.fromEntries(Object.entries(weights).map(([k, v]) => [k, Number(v || 0)])),
      }),
    onSuccess: () => {
      notify('Draft rule created; test it before activation');
      void qc.invalidateQueries({ queryKey: ['proximity-rules'] });
      onClose();
    },
  });
  return (
    <Modal
      open
      onClose={onClose}
      title="New proximity rule (draft)"
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="rule-form" className="btn btn-primary" disabled={!name.trim() || m.isPending}>
            Create draft
          </button>
        </>
      }
    >
      <form
        id="rule-form"
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          m.mutate();
        }}
      >
        <InlineError error={m.error} />
        <div className="form-grid">
          <div className="field">
            <label htmlFor="pr-name">Name</label>
            <input id="pr-name" type="text" required value={name} onChange={(e) => setName(e.target.value)} data-autofocus />
          </div>
          <div className="field">
            <label htmlFor="pr-ls">Landscape</label>
            <select id="pr-ls" value={ls} onChange={(e) => setLs(e.target.value)}>
              <option value="">Tenant-wide</option>
              {landscapes.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="pr-min">Minimum proximity to map (0-1)</label>
            <input id="pr-min" type="number" min={0} max={1} step={0.05} value={minP} onChange={(e) => setMinP(e.target.value)} />
          </div>
        </div>
        <fieldset>
          <legend>Dimension weights</legend>
          <div className="form-grid">
            {DIMS.map((d) => (
              <div className="field" key={d}>
                <label htmlFor={`pr-w-${d}`}>{humanize(d)}</label>
                <input id={`pr-w-${d}`} type="number" min={0} step={0.05} value={weights[d]} onChange={(e) => setWeights({ ...weights, [d]: e.target.value })} />
              </div>
            ))}
          </div>
        </fieldset>
      </form>
    </Modal>
  );
}

export function ProximityTab() {
  const qc = useQueryClient();
  const { notify } = useToast();
  const { landscapes } = useLandscape();
  const q = useQuery({ queryKey: ['proximity-rules'], queryFn: api.proximityRules });
  const [creating, setCreating] = useState(false);
  const [results, setResults] = useState<{ rule: ProximityRule; pairs: ProximityTestPair[] } | null>(null);
  const test = useMutation({
    mutationFn: (r: ProximityRule) => api.testProximityRule(r.id),
    onSuccess: (res, r) => {
      setResults({ rule: r, pairs: res.pairs });
      void qc.invalidateQueries({ queryKey: ['proximity-rules'] });
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  const activate = useMutation({
    mutationFn: (id: string) => api.activateProximityRule(id),
    onSuccess: () => {
      notify('Rule activated; previous active rule retired');
      void qc.invalidateQueries({ queryKey: ['proximity-rules'] });
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  return (
    <div className="stack">
      <div>
        <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
          <Plus size={15} aria-hidden /> New rule
        </button>
      </div>
      <QueryView query={q} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No proximity rules" />}>
        {(rules) => (
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Proximity rules</caption>
              <thead>
                <tr>
                  <th scope="col">Rule</th>
                  <th scope="col">Landscape</th>
                  <th scope="col">Status</th>
                  <th scope="col">Weights</th>
                  <th scope="col" className="num">
                    Min
                  </th>
                  <th scope="col">Tested</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <strong>{r.name}</strong> <span className="tiny muted">v{r.version}</span>
                    </td>
                    <td>{landscapes.find((l) => l.id === r.landscape_id)?.name ?? (r.landscape_id ? r.landscape_id.slice(0, 8) : 'Tenant-wide')}</td>
                    <td>
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="small">
                      {Object.entries(r.weights)
                        .map(([k, v]) => `${humanize(k)} ${v}`)
                        .join(', ')}
                    </td>
                    <td className="num">{r.min_proximity}</td>
                    <td className="small nowrap">{r.test_results?.tested_at ? fmtDateTime(r.test_results.tested_at) : 'Not tested'}</td>
                    <td>
                      <div className="btn-group">
                        <button type="button" className="btn btn-sm" onClick={() => test.mutate(r)} disabled={test.isPending}>
                          <FlaskConical size={13} aria-hidden /> Test
                        </button>
                        {r.status !== 'active' ? (
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => activate.mutate(r.id)}
                            disabled={!r.test_results?.tested_at || activate.isPending}
                            title={!r.test_results?.tested_at ? 'Test the rule against sample assets first' : undefined}
                          >
                            <Power size={13} aria-hidden /> Activate
                          </button>
                        ) : null}
                        {r.test_results?.pairs?.length ? (
                          <button type="button" className="btn btn-sm btn-ghost" onClick={() => setResults({ rule: r, pairs: r.test_results?.pairs ?? [] })}>
                            Last results
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </QueryView>
      {creating ? <CreateRule onClose={() => setCreating(false)} /> : null}
      <Modal open={Boolean(results)} onClose={() => setResults(null)} title={`Test results: ${results?.rule.name ?? ''}`} wide>
        {results ? <PairsTable pairs={results.pairs} /> : null}
      </Modal>
    </div>
  );
}
