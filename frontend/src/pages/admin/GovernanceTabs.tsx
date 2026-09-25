import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/endpoints';
import type { TenantSettings } from '../../api/types';
import { EmptyState, InlineError, QueryView } from '../../components/States';
import { humanize } from '../../lib/format';
import { useToast } from '../../lib/toastContext';

export function ModelsTab() {
  const q = useQuery({ queryKey: ['admin-models'], queryFn: api.models });
  return (
    <QueryView query={q}>
      {(m) => (
        <div className="grid grid-2">
          <section className="card" aria-labelledby="mc-h">
            <h2 id="mc-h">Model configuration</h2>
            <dl className="kv small">
              {Object.entries(m.config).map(([k, v]) => (
                <div key={k} style={{ display: 'contents' }}>
                  <dt>{humanize(k)}</dt>
                  <dd className="mono">{String(v)}</dd>
                </div>
              ))}
            </dl>
          </section>
          <section className="card" aria-labelledby="pv-h">
            <h2 id="pv-h">Prompt / workflow versions</h2>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Workflow</th>
                    <th scope="col">Version</th>
                    <th scope="col">Hash</th>
                  </tr>
                </thead>
                <tbody>
                  {m.prompts.map((p) => (
                    <tr key={p.id}>
                      <td>{p.id}</td>
                      <td>{p.version}</td>
                      <td className="mono small" title={p.hash}>
                        {p.hash.slice(0, 12)}...
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section className="card" aria-labelledby="mu-h" style={{ gridColumn: '1 / -1' }}>
            <h2 id="mu-h">Generation usage (30 days)</h2>
            {m.usage_30d.length === 0 ? (
              <EmptyState title="No generations recorded" />
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Workflow</th>
                      <th scope="col">Served model</th>
                      <th scope="col">Status</th>
                      <th scope="col" className="num">
                        Calls
                      </th>
                      <th scope="col" className="num">
                        Avg latency (ms)
                      </th>
                      <th scope="col" className="num">
                        Cost (USD)
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.usage_30d.map((u, i) => (
                      <tr key={i}>
                        <td>{u.workflow}</td>
                        <td>{u.model}</td>
                        <td>{u.status}</td>
                        <td className="num">{u.calls}</td>
                        <td className="num">{u.avg_latency_ms}</td>
                        <td className="num">{u.cost_usd.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}
    </QueryView>
  );
}

const RETENTION = ['ask_sessions', 'notifications', 'generation_records', 'usage_records', 'feedback'];

function SettingsForm({ data }: { data: TenantSettings }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const s = data.tenant.settings ?? {};
  const [budget, setBudget] = useState(String(s.llm_monthly_budget_usd ?? ''));
  const [ret, setRet] = useState<Record<string, string>>(() => Object.fromEntries(RETENTION.map((k) => [k, String(s.retention_days?.[k] ?? '')])));
  const m = useMutation({
    mutationFn: () =>
      api.patchSettings({
        llm_monthly_budget_usd: budget === '' ? undefined : Number(budget),
        retention_days: Object.fromEntries(Object.entries(ret).filter(([, v]) => v !== '').map(([k, v]) => [k, Number(v)])),
      }),
    onSuccess: () => {
      notify('Settings saved');
      void qc.invalidateQueries({ queryKey: ['admin-settings'] });
    },
  });
  return (
    <form
      className="card stack"
      onSubmit={(e) => {
        e.preventDefault();
        m.mutate();
      }}
    >
      <h2>Tenant settings: {data.tenant.name}</h2>
      <InlineError error={m.error} />
      <div className="field" style={{ maxWidth: 280 }}>
        <label htmlFor="st-budget">Monthly LLM budget (USD)</label>
        <input id="st-budget" type="number" min={0} value={budget} onChange={(e) => setBudget(e.target.value)} />
      </div>
      <fieldset>
        <legend>Retention by data class (days, minimum 7; blank = platform default)</legend>
        <div className="form-grid">
          {RETENTION.map((k) => (
            <div className="field" key={k}>
              <label htmlFor={`ret-${k}`}>{humanize(k)}</label>
              <input id={`ret-${k}`} type="number" min={7} value={ret[k]} onChange={(e) => setRet({ ...ret, [k]: e.target.value })} />
            </div>
          ))}
        </div>
      </fieldset>
      <p className="small">
        Training on customer data: <strong>{data.allow_training_on_customer_data ? 'Allowed' : 'Not allowed'}</strong> (contractual; not configurable here).
      </p>
      <div>
        <button type="submit" className="btn btn-primary" disabled={m.isPending}>
          Save settings
        </button>
      </div>
    </form>
  );
}

export function SettingsTab() {
  const q = useQuery({ queryKey: ['admin-settings'], queryFn: api.settings });
  return <QueryView query={q}>{(d) => <SettingsForm data={d} />}</QueryView>;
}

export function UsageTab() {
  const [days, setDays] = useState(30);
  const q = useQuery({ queryKey: ['admin-usage', days], queryFn: () => api.usage(days) });
  return (
    <div className="stack">
      <div className="field" style={{ maxWidth: 200 }}>
        <label htmlFor="us-days">Window</label>
        <select id="us-days" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 30, 90, 365].map((d) => (
            <option key={d} value={d}>
              Last {d} days
            </option>
          ))}
        </select>
      </div>
      <QueryView query={q}>
        {(u) => {
          const total = u.items.reduce((a, b) => a + b.cost_usd, 0);
          return (
            <div className="stack">
              <div className="grid grid-3">
                <div className="card stat">
                  <span className="value">${total.toFixed(2)}</span>
                  <span className="label">Spend in window</span>
                </div>
                <div className="card stat">
                  <span className="value">{u.budget_usd !== null ? `$${u.budget_usd}` : '-'}</span>
                  <span className="label">Monthly budget</span>
                </div>
                <div className="card stat">
                  <span className="value">{u.budget_usd ? `${((total / u.budget_usd) * 100).toFixed(1)}%` : '-'}</span>
                  <span className="label">Of budget used</span>
                </div>
              </div>
              {u.items.length === 0 ? (
                <div className="card">
                  <EmptyState title="No metered usage in this window" />
                </div>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <caption className="sr-only">Usage by component</caption>
                    <thead>
                      <tr>
                        <th scope="col">Kind</th>
                        <th scope="col">Component</th>
                        <th scope="col">Model</th>
                        <th scope="col" className="num">
                          Input units
                        </th>
                        <th scope="col" className="num">
                          Output units
                        </th>
                        <th scope="col" className="num">
                          Cost (USD)
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {u.items.map((it, i) => (
                        <tr key={i}>
                          <td>{it.kind}</td>
                          <td>{it.component}</td>
                          <td>{it.model ?? '-'}</td>
                          <td className="num">{it.input_units.toLocaleString()}</td>
                          <td className="num">{it.output_units.toLocaleString()}</td>
                          <td className="num">{it.cost_usd.toFixed(4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          );
        }}
      </QueryView>
    </div>
  );
}
