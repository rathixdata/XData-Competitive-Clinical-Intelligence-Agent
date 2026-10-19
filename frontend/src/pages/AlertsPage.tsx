import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BellRing, FlaskConical, Pencil, Plus, Trash2 } from 'lucide-react';
import { api } from '../api/endpoints';
import { CHANNELS, type AlertPolicy, type AlertPolicyInput, type AlertPreview, type Channel } from '../api/types';
import { PERMS, useAuth } from '../auth/context';
import { StatusBadge } from '../components/Badges';
import { Modal } from '../components/Dialog';
import { EmptyState, InlineError, QueryView } from '../components/States';
import { Tabs } from '../components/Tabs';
import { useLandscape } from '../state/landscapeContext';
import { fmtDateTime, fmtRelative } from '../lib/format';
import { CADENCE_LABELS, channelLabel, eventTypeLabel, notificationKindLabel, statusLabel } from '../lib/labels';
import { errorMessage, useToast } from '../lib/toastContext';

function blankPolicy(landscapeId?: string): AlertPolicyInput {
  return {
    name: '',
    landscape_id: landscapeId ?? null,
    cadence: 'daily',
    min_score: 70,
    event_types: [],
    entity_ids: [],
    watchlist_id: null,
    channels: ['web'],
    destinations: { email: [], slack_webhook: null, teams_webhook: null, webhook_url: null },
    active: true,
  };
}

function PreviewBox({ preview }: { preview: AlertPreview }) {
  return (
    <div className="banner banner-info" role="status" aria-live="polite">
      <div>
        <p>
          <strong>Expected volume:</strong> about {preview.estimated_deliveries_per_week} messages per week ({preview.events_per_week} matching changes per week;{' '}
          {preview.matching_events} matched in the last {preview.window_days} days).
        </p>
        {Object.keys(preview.by_band).length ? (
          <p className="small">
            By priority:{' '}
            {Object.entries(preview.by_band)
              .map(([k, v]) => `${k} ${v}`)
              .join(', ')}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function PolicyForm({ initial, policyId, onClose }: { initial: AlertPolicyInput; policyId?: string; onClose: () => void }) {
  const { landscapes } = useLandscape();
  const qc = useQueryClient();
  const { notify } = useToast();
  const [p, setP] = useState<AlertPolicyInput>(initial);
  const [emails, setEmails] = useState(initial.destinations.email.join(', '));
  const facets = useQuery({ queryKey: ['facets', p.landscape_id ?? null], queryFn: () => api.facets(p.landscape_id ?? undefined) });
  const watchlists = useQuery({ queryKey: ['watchlists'], queryFn: api.watchlists });
  const body = (): AlertPolicyInput => ({
    ...p,
    destinations: {
      email: emails.split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean),
      slack_webhook: p.destinations.slack_webhook || null,
      teams_webhook: p.destinations.teams_webhook || null,
      webhook_url: p.destinations.webhook_url || null,
    },
  });
  const preview = useMutation({
    mutationFn: () =>
      api.previewPolicy({ landscape_id: p.landscape_id, cadence: p.cadence, min_score: p.min_score, event_types: p.event_types, entity_ids: p.entity_ids, watchlist_id: p.watchlist_id, days: 90 }),
  });
  const save = useMutation({
    mutationFn: () => (policyId ? api.updatePolicy(policyId, body()) : api.createPolicy(body())),
    onSuccess: () => {
      notify(policyId ? 'Alert rule updated' : 'Alert rule created');
      void qc.invalidateQueries({ queryKey: ['policies'] });
      onClose();
    },
  });
  const toggleChannel = (c: Channel) => setP({ ...p, channels: p.channels.includes(c) ? p.channels.filter((x) => x !== c) : [...p.channels, c] });
  const d = p.destinations;
  return (
    <Modal
      open
      wide
      onClose={onClose}
      title={policyId ? 'Edit alert rule' : 'New alert rule'}
      footer={
        <>
          <button type="button" className="btn" onClick={() => preview.mutate()} disabled={preview.isPending} title="Estimate how many alerts this rule would send per week">
            Estimate volume
          </button>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="policy-form" className="btn btn-primary" disabled={!p.name.trim() || p.channels.length === 0 || save.isPending}>
            Save alert rule
          </button>
        </>
      }
    >
      <form
        id="policy-form"
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <InlineError error={save.error ?? preview.error} />
        <p className="small muted" style={{ margin: 0 }}>
          An alert rule decides which changes you are told about, how often, and where (in-app, email, Slack...). Use &ldquo;Estimate volume&rdquo; to avoid too many alerts.
        </p>
        {preview.data ? <PreviewBox preview={preview.data} /> : null}
        <div className="form-grid">
          <div className="field">
            <label htmlFor="ap-name">Rule name</label>
            <input id="ap-name" type="text" required value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} data-autofocus />
          </div>
          <div className="field">
            <label htmlFor="ap-ls">Market (landscape)</label>
            <select id="ap-ls" value={p.landscape_id ?? ''} onChange={(e) => setP({ ...p, landscape_id: e.target.value || null })}>
              <option value="">All markets</option>
              {landscapes.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="ap-cad">How often</label>
            <select id="ap-cad" value={p.cadence} onChange={(e) => setP({ ...p, cadence: e.target.value as AlertPolicyInput['cadence'] })}>
              <option value="immediate">Immediately</option>
              <option value="daily">Daily digest</option>
              <option value="weekly">Weekly digest</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="ap-min">Minimum importance score (0-100)</label>
            <input id="ap-min" type="number" min={0} max={100} value={p.min_score} onChange={(e) => setP({ ...p, min_score: Number(e.target.value) })} />
          </div>
          <div className="field">
            <label htmlFor="ap-wl">Watchlist (optional)</label>
            <select id="ap-wl" value={p.watchlist_id ?? ''} onChange={(e) => setP({ ...p, watchlist_id: e.target.value || null })}>
              <option value="">None</option>
              {(watchlists.data ?? []).map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </div>
          <label className="checkbox">
            <input type="checkbox" checked={p.active} onChange={(e) => setP({ ...p, active: e.target.checked })} /> Rule is switched on
          </label>
        </div>
        <fieldset>
          <legend>Kinds of change (leave all unticked for every kind)</legend>
          <div className="row">
            {(facets.data?.type ?? []).map((t) => (
              <label key={t.value} className="checkbox">
                <input
                  type="checkbox"
                  checked={p.event_types.includes(t.value)}
                  onChange={(e) => setP({ ...p, event_types: e.target.checked ? [...p.event_types, t.value] : p.event_types.filter((x) => x !== t.value) })}
                />
                {eventTypeLabel(t.value)}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend>Where to send alerts</legend>
          <div className="row">
            {CHANNELS.map((c) => (
              <label key={c} className="checkbox">
                <input type="checkbox" checked={p.channels.includes(c)} onChange={() => toggleChannel(c)} />
                {channelLabel(c)}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="grid grid-2">
          {p.channels.includes('email') ? (
            <div className="field">
              <label htmlFor="ap-email">Email recipients</label>
              <input id="ap-email" type="text" value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="a@example.com, b@example.com" />
            </div>
          ) : null}
          {p.channels.includes('slack') ? (
            <div className="field">
              <label htmlFor="ap-slack">Slack webhook URL</label>
              <input
                id="ap-slack"
                type="url"
                value={d.slack_webhook ?? ''}
                placeholder={policyId ? 'Leave blank to re-enter (stored encrypted)' : 'https://hooks.slack.com/...'}
                onChange={(e) => setP({ ...p, destinations: { ...d, slack_webhook: e.target.value } })}
              />
            </div>
          ) : null}
          {p.channels.includes('teams') ? (
            <div className="field">
              <label htmlFor="ap-teams">Teams webhook URL</label>
              <input id="ap-teams" type="url" value={d.teams_webhook ?? ''} onChange={(e) => setP({ ...p, destinations: { ...d, teams_webhook: e.target.value } })} />
            </div>
          ) : null}
          {p.channels.includes('webhook') ? (
            <div className="field">
              <label htmlFor="ap-hook">Webhook URL</label>
              <input id="ap-hook" type="url" value={d.webhook_url ?? ''} onChange={(e) => setP({ ...p, destinations: { ...d, webhook_url: e.target.value } })} />
            </div>
          ) : null}
        </div>
        {policyId ? <p className="small muted">For security, Slack/Teams/webhook addresses are stored encrypted and never shown again; re-enter them when editing this rule.</p> : null}
      </form>
    </Modal>
  );
}

function toInput(pol: AlertPolicy): AlertPolicyInput {
  return {
    name: pol.name,
    landscape_id: pol.landscape_id,
    cadence: pol.cadence,
    min_score: pol.min_score,
    event_types: pol.event_types ?? [],
    entity_ids: pol.entity_ids ?? [],
    watchlist_id: pol.watchlist_id,
    channels: pol.channels,
    // masked secrets ("configured") cannot be round-tripped; the user must re-enter them
    destinations: { email: pol.destinations.email ?? [], slack_webhook: null, teams_webhook: null, webhook_url: null },
    active: pol.active,
  };
}

function Policies() {
  const { can } = useAuth();
  const { landscapeId } = useLandscape();
  const qc = useQueryClient();
  const { notify } = useToast();
  const q = useQuery({ queryKey: ['policies'], queryFn: api.policies });
  const [editing, setEditing] = useState<{ initial: AlertPolicyInput; id?: string } | null>(null);
  const test = useMutation({
    mutationFn: (id: string) => api.testPolicy(id),
    onSuccess: (r) => {
      notify(`Test sent: ${Object.entries(r.results).map(([k, v]) => `${channelLabel(k)} ${v}`).join(', ')}`);
      void qc.invalidateQueries({ queryKey: ['inbox'] });
      void qc.invalidateQueries({ queryKey: ['deliveries'] });
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  const del = useMutation({
    mutationFn: (id: string) => api.deletePolicy(id),
    onSuccess: () => {
      notify('Alert rule switched off');
      void qc.invalidateQueries({ queryKey: ['policies'] });
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  const canWrite = can(PERMS.alertWrite);
  return (
    <div className="stack">
      {canWrite ? (
        <div>
          <button type="button" className="btn btn-primary" onClick={() => setEditing({ initial: blankPolicy(landscapeId) })}>
            <Plus size={15} aria-hidden /> New alert rule
          </button>
        </div>
      ) : null}
      <QueryView query={q} isEmpty={(d) => d.length === 0} empty={
          <div className="card">
            <EmptyState title="No alert rules yet">
              {canWrite ? 'Click "New alert rule" to be told (in-app, by email, Slack or Teams) when an important change happens.' : 'Ask an analyst to set up an alert rule for you.'}
            </EmptyState>
          </div>
        }>
        {(items) => (
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Your alert rules</caption>
              <thead>
                <tr>
                  <th scope="col">Rule</th>
                  <th scope="col">How often</th>
                  <th scope="col" className="num" title="Minimum importance score (0-100)">
                    Min. score
                  </th>
                  <th scope="col">Sent to</th>
                  <th scope="col">Status</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((pol) => (
                  <tr key={pol.id}>
                    <td>
                      <strong>{pol.name}</strong>
                      {pol.event_types?.length ? <div className="tiny muted">{pol.event_types.map(eventTypeLabel).join(', ')}</div> : null}
                    </td>
                    <td>{CADENCE_LABELS[pol.cadence] ?? pol.cadence}</td>
                    <td className="num">{pol.min_score}</td>
                    <td>
                      {pol.channels.map((c) => (
                        <span key={c} className="badge badge-neutral" style={{ marginRight: 4 }}>
                          {channelLabel(c)}
                          {c !== 'web' && c !== 'email' && pol.destinations[`${c === 'webhook' ? 'webhook_url' : `${c}_webhook`}` as 'slack_webhook'] ? ' (configured)' : ''}
                        </span>
                      ))}
                    </td>
                    <td>
                      <StatusBadge status={pol.active ? 'active' : 'inactive'} />
                    </td>
                    <td>
                      {canWrite ? (
                        <div className="btn-group">
                          <button type="button" className="btn btn-sm" onClick={() => setEditing({ initial: toInput(pol), id: pol.id })} aria-label={`Edit ${pol.name}`}>
                            <Pencil size={13} aria-hidden /> Edit
                          </button>
                          <button type="button" className="btn btn-sm" onClick={() => test.mutate(pol.id)} disabled={test.isPending} aria-label={`Send a test alert for ${pol.name}`} title="Send a test message to check the rule works">
                            <FlaskConical size={13} aria-hidden /> Send test
                          </button>
                          {pol.active ? (
                            <button type="button" className="btn btn-sm" onClick={() => del.mutate(pol.id)} aria-label={`Switch off ${pol.name}`} title="Stop sending alerts for this rule">
                              <Trash2 size={13} aria-hidden /> Switch off
                            </button>
                          ) : null}
                        </div>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </QueryView>
      {editing ? <PolicyForm initial={editing.initial} policyId={editing.id} onClose={() => setEditing(null)} /> : null}
    </div>
  );
}

function Deliveries() {
  const [status, setStatus] = useState('');
  const [channel, setChannel] = useState('');
  const [offset, setOffset] = useState(0);
  const q = useQuery({ queryKey: ['deliveries', status, channel, offset], queryFn: () => api.deliveries({ status: status || undefined, channel: channel || undefined, offset, limit: 50 }) });
  return (
    <div className="stack">
      <div className="form-grid">
        <div className="field">
          <label htmlFor="dl-status">Status</label>
          <select id="dl-status" value={status} onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}>
            <option value="">Any</option>
            {['pending', 'sent', 'failed', 'dead', 'read'].map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="dl-ch">Channel</label>
          <select id="dl-ch" value={channel} onChange={(e) => {
              setChannel(e.target.value);
              setOffset(0);
            }}>
            <option value="">Any</option>
            {CHANNELS.map((c) => (
              <option key={c} value={c}>
                {channelLabel(c)}
              </option>
            ))}
          </select>
        </div>
      </div>
      <QueryView query={q} isEmpty={(d) => d.items.length === 0} empty={
          <div className="card">
            <EmptyState title="No alerts sent yet">Every alert message the system sends (in-app, email, Slack, Teams) is logged here, including failures.</EmptyState>
          </div>
        }>
        {(d) => (
          <>
            <div className="table-wrap">
              <table className="table">
                <caption className="sr-only">Sent alerts log</caption>
                <thead>
                  <tr>
                    <th scope="col">Created</th>
                    <th scope="col">Message</th>
                    <th scope="col">Type</th>
                    <th scope="col">Sent via</th>
                    <th scope="col">Status</th>
                    <th scope="col" className="num">
                      Attempts
                    </th>
                    <th scope="col">Sent</th>
                    <th scope="col">Problem (if any)</th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((n) => (
                    <tr key={n.id}>
                      <td className="nowrap">{fmtDateTime(n.created_at)}</td>
                      <td>{n.payload.title ?? '-'}</td>
                      <td>{notificationKindLabel(n.kind)}</td>
                      <td>{channelLabel(n.channel)}</td>
                      <td>
                        <StatusBadge status={n.status} />
                      </td>
                      <td className="num">{n.attempts}</td>
                      <td className="nowrap">{n.sent_at ? fmtDateTime(n.sent_at) : '-'}</td>
                      <td className="small">{n.last_error ?? '-'}</td>
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

function Inbox() {
  const qc = useQueryClient();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const q = useQuery({ queryKey: ['inbox'], queryFn: () => api.inbox(false) });
  const mark = useMutation({ mutationFn: api.markRead, onSuccess: () => qc.invalidateQueries({ queryKey: ['inbox'] }) });
  const items = (q.data ?? []).filter((n) => !unreadOnly || n.status !== 'read');
  return (
    <div className="stack">
      <div className="row-between">
        <label className="checkbox">
          <input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} /> Show unread only
        </label>
        {(q.data ?? []).some((n) => n.status !== 'read') ? (
          <button
            type="button"
            className="btn btn-sm"
            onClick={async () => {
              for (const n of (q.data ?? []).filter((x) => x.status !== 'read')) await api.markRead(n.id);
              void qc.invalidateQueries({ queryKey: ['inbox'] });
            }}
          >
            Mark all as read
          </button>
        ) : null}
      </div>
      <QueryView query={{ ...q, data: q.data ? items : undefined }} isEmpty={(d) => d.length === 0} empty={
          <div className="card">
            <EmptyState title={unreadOnly ? 'No unread notifications' : 'Your inbox is empty'}>
              Notifications from your alert rules, and changes escalated to you, will appear here. Set up rules in the &ldquo;Alert rules&rdquo; tab.
            </EmptyState>
          </div>
        }>
        {(list) => (
          <ul className="list-plain card">
            {list.map((n) => {
              const evId = (n.payload.event_id as string | undefined) ?? n.intel_event_ids[0];
              return (
                <li key={n.id} className="row-between" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
                  <div className="stack-sm" style={{ gap: 2, minWidth: 0 }}>
                    <div className="row">
                      {n.status !== 'read' ? <span className="badge badge-info">Unread</span> : <span className="badge badge-neutral">Read</span>}
                      <span className="badge badge-neutral">{notificationKindLabel(n.kind)}</span>
                      <span className="small muted">{fmtRelative(n.created_at)}</span>
                    </div>
                    {evId ? (
                      <Link to={`/events/${evId}`} onClick={() => n.status !== 'read' && mark.mutate(n.id)}>
                        {n.payload.title ?? 'Notification'}
                      </Link>
                    ) : (
                      <span className="strong">{n.payload.title ?? 'Notification'}</span>
                    )}
                    {n.payload.note ? <span className="small">Note from colleague: {n.payload.note}</span> : null}
                    {n.payload.verified_change?.length ? <span className="small muted">{n.payload.verified_change.join(' ')}</span> : null}
                  </div>
                  {n.status !== 'read' ? (
                    <button type="button" className="btn btn-sm" onClick={() => mark.mutate(n.id)}>
                      Mark read
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </QueryView>
    </div>
  );
}

export function AlertsPage() {
  const [sp, setSp] = useSearchParams();
  const tab = sp.get('tab') ?? 'inbox';
  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            <BellRing size={20} aria-hidden /> Alerts &amp; inbox
          </h1>
          <p>
            Your notifications, plus the alert rules that decide which important changes you (or your team) are told about, how often, and where - in the app, by email, Slack
            or Teams.
          </p>
        </div>
      </div>
      <Tabs
        label="Alerts sections"
        active={tab}
        onChange={(t) => setSp({ tab: t }, { replace: true })}
        tabs={[
          { id: 'inbox', label: 'My inbox' },
          { id: 'policies', label: 'Alert rules' },
          { id: 'deliveries', label: 'Sent alerts log' },
        ]}
      />
      <p className="small muted tab-intro">
        {tab === 'inbox'
          ? 'Notifications sent to you inside the app. Click one to open the change it is about.'
          : tab === 'policies'
            ? 'Rules that decide which changes trigger an alert, how often, and where it is sent.'
            : 'A record of every alert message sent, and whether it was delivered.'}
      </p>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === 'inbox' ? <Inbox /> : tab === 'policies' ? <Policies /> : <Deliveries />}
      </div>
    </>
  );
}
