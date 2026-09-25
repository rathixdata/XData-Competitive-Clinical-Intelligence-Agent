import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertOctagon, ArrowLeft, CheckCheck, ExternalLink, Flag, History, PencilLine, RefreshCw, ShieldAlert, ThumbsUp } from 'lucide-react';
import { api } from '../../api/endpoints';
import type { Artifact, ChangeRecord, Claim, EventDetail, EvidenceLink, SourceDocumentRef } from '../../api/types';
import { PERMS, useAuth } from '../../auth/context';
import { BandBadge, ReviewBadge, StatusBadge } from '../../components/Badges';
import { Modal } from '../../components/Dialog';
import { EvidenceDrawer, RightsBlock } from '../../components/EvidenceDrawer';
import { ImpactList } from '../../components/ImpactPath';
import { ExplanationPanel } from '../../components/ExplanationPanel';
import { ScoreExplanation } from '../../components/ScoreExplanation';
import { StatementCard, StatementLegend } from '../../components/Statement';
import { EmptyState, ErrorState, InlineError, Loading } from '../../components/States';
import { SECTION_LABELS, SECTION_ORDER } from '../../components/statementMeta';
import { fmtDate, fmtDateTime, fmtValue, humanize, shortId } from '../../lib/format';
import { errorMessage, useToast } from '../../lib/toastContext';
import { FeedbackPanel } from './FeedbackPanel';
import { NarrativeEditor } from './NarrativeEditor';

function DiffTable({ changes }: { changes: ChangeRecord[] }) {
  if (changes.length === 0) return <EmptyState title="No field-level changes recorded for this event" />;
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">Field changes between source snapshots (old value to new value)</caption>
        <thead>
          <tr>
            <th scope="col">Field</th>
            <th scope="col">Previous value</th>
            <th scope="col">New value</th>
            <th scope="col">Snapshots compared</th>
            <th scope="col">Source</th>
          </tr>
        </thead>
        <tbody>
          {changes.map((c) => (
            <tr key={c.id}>
              <th scope="row" style={{ fontWeight: 600 }}>
                {humanize(c.field)}
                <div className="tiny muted">{humanize(c.change_type)}</div>
                {c.magnitude && typeof c.magnitude.pct_change === 'number' ? (
                  <div className="tiny muted">
                    {(c.magnitude.pct_change as number) > 0 ? '+' : ''}
                    {(c.magnitude.pct_change as number).toFixed(0)}%
                  </div>
                ) : null}
              </th>
              <td>
                <span className="sr-only">Previous: </span>
                <span className="diff-old">{fmtValue(c.old_value)}</span>
              </td>
              <td>
                <span className="sr-only">New: </span>
                <span className="diff-new">{fmtValue(c.new_value)}</span>
              </td>
              <td className="small">
                {c.from_snapshot ? (
                  <div>
                    v{c.from_snapshot.version} retrieved {fmtDate(c.from_snapshot.retrieved_at)}
                  </div>
                ) : (
                  <div className="muted">First observation</div>
                )}
                {c.to_snapshot ? (
                  <div>
                    to v{c.to_snapshot.version} retrieved {fmtDate(c.to_snapshot.retrieved_at)}
                  </div>
                ) : null}
              </td>
              <td className="small">
                {c.source_document?.uri ? (
                  <a href={c.source_document.uri} target="_blank" rel="noreferrer noopener">
                    {c.source_document.source} record <ExternalLink size={11} aria-hidden />
                    <span className="sr-only"> (opens in a new tab)</span>
                  </a>
                ) : (
                  (c.source ?? '-')
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ValidationBadges({ narrative }: { narrative: Artifact }) {
  const v = narrative.validation;
  const counts = v?.counts ?? {};
  const withheld = v?.withheld?.length ?? 0;
  const fallback = Boolean(v?.fallback_used || narrative.content.fallback_of);
  return (
    <div className="row" aria-label="Validation summary">
      <span className="badge badge-success">{counts.supported ?? 0} facts supported by evidence</span>
      {counts.partially_supported ? <span className="badge badge-warning">{counts.partially_supported} partially supported</span> : null}
      <span className={`badge ${withheld ? 'badge-warning' : 'badge-neutral'}`}>
        {withheld} statement{withheld === 1 ? '' : 's'} withheld
      </span>
      {counts.inference ? <span className="badge badge-inferred">{counts.inference} AI interpretations</span> : null}
      {narrative.publishable ? (
        <span className="badge badge-success">Publishable</span>
      ) : (
        <span className="badge badge-danger">
          <ShieldAlert size={12} aria-hidden /> Blocked
        </span>
      )}
      {fallback ? <span className="badge badge-warning">Fallback used (deterministic output)</span> : null}
      {v?.validator_version ? <span className="tiny muted">validator {v.validator_version}</span> : null}
    </div>
  );
}

function evidenceMap(n: Artifact): Record<string, EvidenceLink> {
  const out: Record<string, EvidenceLink> = { ...(n.content.evidence ?? {}) };
  for (const c of n.claims) for (const l of c.evidence_links ?? []) if (l.evidence_id && !out[l.evidence_id]) out[l.evidence_id] = l;
  return out;
}

function groupClaims(claims: Claim[]): [string, Claim[]][] {
  const by = new Map<string, Claim[]>();
  for (const c of [...claims].sort((a, b) => a.ordinal - b.ordinal)) {
    if (!by.has(c.section)) by.set(c.section, []);
    by.get(c.section)?.push(c);
  }
  return [...by.entries()].sort((a, b) => {
    const ia = SECTION_ORDER.indexOf(a[0]);
    const ib = SECTION_ORDER.indexOf(b[0]);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
}

export function NarrativeBody({ narrative, onOpenEvidence }: { narrative: Artifact; onOpenEvidence: (l: EvidenceLink) => void }) {
  const ev = useMemo(() => evidenceMap(narrative), [narrative]);
  const groups = groupClaims(narrative.claims);
  if (groups.length === 0) return <EmptyState title="No statements in this narrative" />;
  return (
    <div className="stack">
      {groups.map(([section, claims]) => (
        <section key={section} aria-label={SECTION_LABELS[section] ?? humanize(section)} className="stack-sm">
          <h3 style={{ margin: 0 }}>{SECTION_LABELS[section] ?? humanize(section)}</h3>
          {claims.map((c) => (
            <StatementCard key={c.id} statement={c} evidence={ev} onOpenEvidence={onOpenEvidence} reviewStatus={c.review_status} />
          ))}
        </section>
      ))}
    </div>
  );
}

function HistoryPanel({ detail, onOpenEvidence }: { detail: EventDetail; onOpenEvidence: (l: EvidenceLink) => void }) {
  const [selected, setSelected] = useState<string | null>(null);
  const eventId = detail.event.id;
  const art = useQuery({ queryKey: ['artifact', eventId, selected], queryFn: () => api.artifact(eventId, selected as string), enabled: Boolean(selected) });
  const current = detail.narrative;
  const hist = [...detail.narrative_history].reverse();
  return (
    <>
      {hist.length === 0 ? (
        <p className="muted small">No narrative versions.</p>
      ) : (
        <ol className="list-plain">
          {hist.map((h) => (
            <li key={h.id} className="row-between">
              <div className="stack-sm" style={{ gap: 2 }}>
                <div className="row">
                  <span className="strong">{fmtDateTime(h.created_at)}</span>
                  {h.id === current?.id ? <span className="badge badge-info">Current</span> : null}
                  <ReviewBadge status={h.review_status} humanEdited={h.is_human_edited} />
                  {!h.publishable ? <span className="badge badge-danger">Blocked</span> : null}
                  {h.fallback_used ? <span className="badge badge-warning">Fallback</span> : null}
                </div>
                <span className="tiny muted">
                  {h.is_human_edited ? `Edited by ${shortId(h.edited_by)}` : 'Machine-generated'} - {h.model_workflow_version}
                  {h.parent_id ? ` - derived from ${shortId(h.parent_id)}` : ''}
                </span>
              </div>
              <button type="button" className="btn btn-sm" onClick={() => setSelected(h.id)}>
                {h.id === current?.id ? 'View' : 'Compare with current'}
              </button>
            </li>
          ))}
        </ol>
      )}
      <Modal open={Boolean(selected)} onClose={() => setSelected(null)} title="Narrative version comparison" wide>
        {art.isLoading ? <Loading /> : art.error ? <ErrorState error={art.error} /> : null}
        {art.data ? (
          <div className="grid grid-2">
            <section className="stack-sm" aria-label="Selected version">
              <h3>
                Selected version ({fmtDateTime(art.data.created_at)}) {art.data.is_human_edited ? <span className="badge badge-human">Human-edited</span> : <span className="badge badge-neutral">Machine original</span>}
              </h3>
              {art.data.edit_reason ? <p className="small">Edit reason: {art.data.edit_reason}</p> : null}
              <NarrativeBody narrative={art.data} onOpenEvidence={onOpenEvidence} />
            </section>
            <section className="stack-sm" aria-label="Current version">
              <h3>
                Current version {current?.is_human_edited ? <span className="badge badge-human">Human-edited</span> : <span className="badge badge-neutral">Machine</span>}
              </h3>
              {current?.edit_reason ? <p className="small">Edit reason: {current.edit_reason}</p> : null}
              {current ? <NarrativeBody narrative={current} onOpenEvidence={onOpenEvidence} /> : <p className="muted">No current narrative</p>}
            </section>
          </div>
        ) : null}
      </Modal>
    </>
  );
}

type ActionKind = 'acknowledge' | 'escalate' | 'approve' | 'request_changes' | 'regenerate';

const ACTION_TEXT: Record<ActionKind, { title: string; confirm: string; help: string }> = {
  acknowledge: { title: 'Acknowledge event', confirm: 'Acknowledge', help: 'Marks the event as seen and triaged by you.' },
  escalate: { title: 'Escalate event', confirm: 'Escalate', help: 'Escalates to stakeholders and sends an in-app notification.' },
  approve: { title: 'Approve narrative', confirm: 'Approve', help: 'Marks the current narrative as analyst-approved.' },
  request_changes: { title: 'Request changes', confirm: 'Request changes', help: 'Returns the narrative to machine (unreviewed) status.' },
  regenerate: {
    title: 'Regenerate interpretation',
    confirm: 'Regenerate',
    help: 'Re-runs retrieval, interpretation and validation with current evidence. Creates a new version.',
  },
};

function ActionDialog({ kind, eventId, onClose }: { kind: ActionKind | null; eventId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const [note, setNote] = useState('');
  const m = useMutation({
    mutationFn: async () => {
      switch (kind) {
        case 'acknowledge':
          return api.acknowledge(eventId, note);
        case 'escalate':
          return api.escalate(eventId, note);
        case 'approve':
          return api.review(eventId, 'approve', note);
        case 'request_changes':
          return api.review(eventId, 'request_changes', note);
        case 'regenerate':
          return api.regenerate(eventId);
        default:
          return null;
      }
    },
    onSuccess: () => {
      notify(`${kind ? ACTION_TEXT[kind].confirm : 'Action'} completed`);
      void qc.invalidateQueries({ queryKey: ['event', eventId] });
      void qc.invalidateQueries({ queryKey: ['events'] });
      void qc.invalidateQueries({ queryKey: ['inbox'] });
      setNote('');
      onClose();
    },
  });
  if (!kind) return null;
  const t = ACTION_TEXT[kind];
  return (
    <Modal
      open
      onClose={onClose}
      title={t.title}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className={`btn ${kind === 'escalate' ? 'btn-danger' : 'btn-primary'}`} onClick={() => m.mutate()} disabled={m.isPending} aria-busy={m.isPending}>
            {m.isPending ? 'Working...' : t.confirm}
          </button>
        </>
      }
    >
      <div className="stack">
        <p>{t.help}</p>
        <InlineError error={m.error} />
        {kind !== 'regenerate' ? (
          <div className="field">
            <label htmlFor="action-note">Note (optional, recorded in the audit log)</label>
            <textarea id="action-note" value={note} onChange={(e) => setNote(e.target.value)} data-autofocus />
          </div>
        ) : null}
      </div>
    </Modal>
  );
}

function SourceDocuments({ changes }: { changes: ChangeRecord[] }) {
  const docs = new Map<string, SourceDocumentRef>();
  for (const c of changes) if (c.source_document) docs.set(c.source_document.id, c.source_document);
  if (docs.size === 0) return <p className="muted small">No source document linked.</p>;
  return (
    <ul className="list-plain">
      {[...docs.values()].map((d) => (
        <li key={d.id} className="stack-sm">
          <strong>{d.title ?? d.uri ?? d.id}</strong>
          <dl className="kv small">
            <dt>Source</dt>
            <dd>{d.source}</dd>
            <dt>Retrieved</dt>
            <dd>{fmtDateTime(d.retrieved_at)}</dd>
            {d.connector_version ? (
              <>
                <dt>Connector</dt>
                <dd>v{d.connector_version}</dd>
              </>
            ) : null}
            {d.checksum ? (
              <>
                <dt>Checksum</dt>
                <dd className="mono" title={d.checksum}>
                  {d.checksum.slice(0, 16)}...
                </dd>
              </>
            ) : null}
            {d.uri ? (
              <>
                <dt>Link</dt>
                <dd>
                  <a href={d.uri} target="_blank" rel="noreferrer noopener">
                    Open source record <ExternalLink size={11} aria-hidden />
                    <span className="sr-only"> (opens in a new tab)</span>
                  </a>
                </dd>
              </>
            ) : null}
          </dl>
          <RightsBlock rights={d.rights} />
          <p className="tiny muted" style={{ margin: 0 }}>
            Disclaimer: third-party source content is shown for reference under the rights above; verify against the original record before external use.
          </p>
        </li>
      ))}
    </ul>
  );
}

export function EventDetailPage() {
  const { id = '' } = useParams();
  const { can } = useAuth();
  const q = useQuery({ queryKey: ['event', id], queryFn: () => api.event(id), enabled: Boolean(id) });
  const [evidence, setEvidence] = useState<EvidenceLink | null>(null);
  const [action, setAction] = useState<ActionKind | null>(null);
  const [editing, setEditing] = useState(false);
  const { notify } = useToast();

  if (q.isLoading) return <Loading label="Loading event" />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  if (!q.data) return null;
  const d = q.data;
  const e = d.event;
  const n = d.narrative;
  const canTriage = can(PERMS.eventTriage);
  const canEdit = can(PERMS.narrativeEdit);

  return (
    <>
      <nav aria-label="Breadcrumb" className="small" style={{ marginBottom: 8 }}>
        <Link to="/feed">
          <ArrowLeft size={13} aria-hidden /> Back to feed
        </Link>
      </nav>
      <header className="stack-sm" style={{ marginBottom: 16 }}>
        <div className="row">
          <BandBadge band={e.band} score={e.materiality_score} />
          <span className="badge badge-neutral">{humanize(e.primary_type)}</span>
          {e.secondary_tags.slice(0, 5).map((t) => (
            <span key={t} className="badge badge-neutral">
              {humanize(t)}
            </span>
          ))}
          <StatusBadge status={e.status} />
          <ReviewBadge status={e.review_status} humanEdited={n?.is_human_edited} />
          <span className="badge badge-neutral">Version {e.version}</span>
        </div>
        <h1 style={{ margin: 0 }}>{n?.content.headline ?? e.title}</h1>
        <p className="small muted" style={{ margin: 0 }}>
          Source: {e.source} - fetched {fmtDateTime(e.source_fetched_at)} - detected {fmtDateTime(e.detected_at)}
          {e.published_at ? ` - published ${fmtDateTime(e.published_at)}` : ''}
          {e.acknowledged_by ? ` - acknowledged by ${shortId(e.acknowledged_by)}` : ''}
        </p>
        {e.update_summary?.length ? (
          <div className="banner banner-info" role="note">
            <History size={16} aria-hidden />
            <p>Updated: {e.update_summary.join('; ')}</p>
          </div>
        ) : null}
        {e.publication_blocked_reason ? (
          <div className="banner banner-danger" role="alert">
            <AlertOctagon size={18} aria-hidden />
            <p>
              <strong>Publication blocked:</strong> {e.publication_blocked_reason}
            </p>
          </div>
        ) : null}
        <div className="btn-group" role="group" aria-label="Event actions">
          {canTriage ? (
            <>
              <button type="button" className="btn" onClick={() => setAction('acknowledge')} disabled={e.status === 'acknowledged'}>
                <CheckCheck size={15} aria-hidden /> Acknowledge
              </button>
              <button type="button" className="btn" onClick={() => setAction('escalate')} disabled={e.status === 'escalated'}>
                <Flag size={15} aria-hidden /> Escalate
              </button>
            </>
          ) : null}
          {canEdit && n ? (
            <>
              <button type="button" className="btn" onClick={() => setAction('approve')} disabled={!n.publishable || n.review_status === 'Approved'}>
                <ThumbsUp size={15} aria-hidden /> Approve narrative
              </button>
              <button type="button" className="btn" onClick={() => setAction('request_changes')}>
                Request changes
              </button>
              <button type="button" className="btn" onClick={() => setEditing(true)}>
                <PencilLine size={15} aria-hidden /> Edit narrative
              </button>
            </>
          ) : null}
          {canEdit ? (
            <button type="button" className="btn" onClick={() => setAction('regenerate')}>
              <RefreshCw size={15} aria-hidden /> Regenerate
            </button>
          ) : null}
          <button
            type="button"
            className="btn btn-ghost"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(window.location.href);
                notify('Event link copied');
              } catch (err) {
                notify(errorMessage(err), 'error');
              }
            }}
          >
            Copy link
          </button>
        </div>
      </header>

      <div className="grid grid-main-side">
        <div className="stack" style={{ gap: 16, minWidth: 0 }}>
          {d.explanation ? (
            <section className="card" aria-labelledby="why-h">
              <div className="card-header">
                <h2 id="why-h">Why am I seeing this?</h2>
              </div>
              <ExplanationPanel x={d.explanation} />
            </section>
          ) : null}

          <section className="card" aria-labelledby="diff-h">
            <div className="card-header">
              <h2 id="diff-h">What changed (verified from source snapshots)</h2>
            </div>
            <DiffTable changes={d.changes} />
          </section>

          <section className="card" aria-labelledby="narr-h">
            <div className="card-header">
              <h2 id="narr-h">Impact narrative</h2>
              {n ? <ReviewBadge status={n.review_status} humanEdited={n.is_human_edited} /> : null}
            </div>
            {n ? (
              <div className="stack">
                <ValidationBadges narrative={n} />
                {n.validation?.blocked_reasons?.length ? (
                  <div className="banner banner-danger" role="alert">
                    <AlertOctagon size={16} aria-hidden />
                    <div>
                      <p>
                        <strong>Blocked reasons:</strong>
                      </p>
                      <ul style={{ margin: 0, paddingLeft: 18 }}>
                        {n.validation.blocked_reasons.map((r) => (
                          <li key={r}>{r}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                ) : null}
                {n.is_human_edited && n.edit_reason ? (
                  <p className="small">
                    <strong>Analyst edit reason:</strong> {n.edit_reason}
                  </p>
                ) : null}
                <StatementLegend />
                <NarrativeBody narrative={n} onOpenEvidence={setEvidence} />
                {n.validation?.withheld?.length ? (
                  <details>
                    <summary className="small">{n.validation.withheld.length} withheld statement(s) (not published; retained for audit)</summary>
                    <ul className="small">
                      {n.validation.withheld.map((w, i) => (
                        <li key={i}>{w.statement}</li>
                      ))}
                    </ul>
                  </details>
                ) : null}
                <p className="tiny muted" style={{ margin: 0 }}>
                  Model / workflow: {n.model_workflow_version}
                </p>
              </div>
            ) : (
              <EmptyState title="No narrative generated yet">{canEdit ? 'Use Regenerate to create one.' : null}</EmptyState>
            )}
          </section>

          <section className="card" aria-labelledby="hist-h">
            <div className="card-header">
              <h2 id="hist-h">Narrative history</h2>
            </div>
            <HistoryPanel detail={d} onOpenEvidence={setEvidence} />
          </section>
        </div>

        <div className="stack" style={{ gap: 16, minWidth: 0 }}>
          <section className="card" aria-labelledby="impact-h">
            <div className="card-header">
              <h2 id="impact-h">Impact path to your assets</h2>
            </div>
            {d.impacts?.length ? <ImpactList impacts={d.impacts} /> : <p className="muted small">Not mapped to any customer asset.</p>}
          </section>
          <section className="card" aria-labelledby="score-h">
            <div className="card-header">
              <h2 id="score-h">Why this score</h2>
              <BandBadge band={e.band} score={e.materiality_score} />
            </div>
            <ScoreExplanation explanation={d.score_explanation} score={e.materiality_score} />
          </section>
          <section className="card" aria-labelledby="src-h">
            <div className="card-header">
              <h2 id="src-h">Source document</h2>
            </div>
            <SourceDocuments changes={d.changes} />
          </section>
          <section className="card" aria-labelledby="fb-h">
            <div className="card-header">
              <h2 id="fb-h">Feedback</h2>
            </div>
            <FeedbackPanel detail={d} />
          </section>
        </div>
      </div>

      <EvidenceDrawer link={evidence} onClose={() => setEvidence(null)} />
      <ActionDialog kind={action} eventId={e.id} onClose={() => setAction(null)} />
      {editing && n ? <NarrativeEditor eventId={e.id} narrative={n} open={editing} onClose={() => setEditing(false)} /> : null}
    </>
  );
}
