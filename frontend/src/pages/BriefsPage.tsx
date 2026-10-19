import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Check, FilePlus2, PencilLine, Send } from 'lucide-react';
import { api } from '../api/endpoints';
import type { BriefContent, ReportDetail, ReportStatus } from '../api/types';
import { PERMS, useAuth } from '../auth/context';
import { BandBadge, BasisBadge, StatusBadge } from '../components/Badges';
import { Modal } from '../components/Dialog';
import { ExportButtons } from '../components/ExportButtons';
import { StatementCard } from '../components/Statement';
import { EmptyState, ErrorState, InlineError, Loading, QueryView } from '../components/States';
import { useLandscape } from '../state/landscapeContext';
import { catalystDate } from '../lib/catalyst';
import { fmtDate, fmtDateTime, isoDay, shortId } from '../lib/format';
import { eventTypeLabel } from '../lib/labels';
import { useToast } from '../lib/toastContext';

const STEPS: { id: ReportStatus; label: string }[] = [
  { id: 'draft', label: 'Draft' },
  { id: 'in_review', label: 'In review' },
  { id: 'approved', label: 'Approved' },
  { id: 'distributed', label: 'Sent' },
];

function Stepper({ status }: { status: ReportStatus }) {
  const idx = STEPS.findIndex((s) => s.id === status);
  return (
    <ol className="progress-steps" aria-label="Brief workflow status">
      {STEPS.map((s, i) => (
        <li key={s.id} className={i < idx ? 'done' : i === idx ? 'active' : ''} aria-current={i === idx ? 'step' : undefined}>
          {i < idx ? <Check size={12} aria-hidden /> : null}
          {i + 1}. {s.label}
          {i === idx ? ' (current)' : ''}
        </li>
      ))}
    </ol>
  );
}

function GenerateBrief({ onDone }: { onDone: (id: string) => void }) {
  const { landscapeId } = useLandscape();
  const today = new Date();
  const weekAgo = new Date(today.getTime() - 7 * 86400_000);
  const [start, setStart] = useState(isoDay(weekAgo));
  const [end, setEnd] = useState(isoDay(today));
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => api.createBrief({ landscape_id: landscapeId as string, period_start: start, period_end: end }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['reports'] });
      onDone(r.id);
    },
  });
  return (
    <form
      className="form-grid"
      onSubmit={(e) => {
        e.preventDefault();
        m.mutate();
      }}
    >
      <div className="field">
        <label htmlFor="b-start">Covering changes from</label>
        <input id="b-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} required />
      </div>
      <div className="field">
        <label htmlFor="b-end">To</label>
        <input id="b-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} required />
      </div>
      <div className="field">
        <button type="submit" className="btn btn-primary" disabled={!landscapeId || m.isPending} aria-busy={m.isPending}>
          <FilePlus2 size={15} aria-hidden /> {m.isPending ? 'Writing the brief...' : 'Create brief'}
        </button>
      </div>
      <div style={{ gridColumn: '1 / -1' }}>
        <InlineError error={m.error} />
      </div>
    </form>
  );
}

export function BriefsListPage() {
  const { landscapeId, landscape } = useLandscape();
  const { can } = useAuth();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ['reports', landscapeId], queryFn: () => api.reports(landscapeId) });
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Executive briefs</h1>
          <p>
            One-page summaries of the most important competitor changes{landscape ? ` in ${landscape.name}` : ''}, written for leadership. The AI drafts a brief, an analyst
            reviews and approves it, then you download it or send it to recipients.
          </p>
        </div>
      </div>
      {can(PERMS.reportWrite) ? (
        <section className="card" aria-labelledby="gen-h" style={{ marginBottom: 16 }}>
          <h2 id="gen-h">Create a brief</h2>
          <p className="small muted section-intro">Pick the period to cover. The brief is drafted from the changes detected in that period; you can edit it before approving.</p>
          <GenerateBrief onDone={(id) => navigate(`/briefs/${id}`)} />
        </section>
      ) : null}
      <QueryView query={q} isEmpty={(d) => d.length === 0} empty={
          <div className="card">
            <EmptyState title="No executive briefs yet">
              {can(PERMS.reportWrite)
                ? 'Click "Create brief" above to generate one from the latest changes.'
                : 'Briefs created by your analysts will appear here once they are drafted.'}
            </EmptyState>
          </div>
        }>
        {(reports) => (
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Executive briefs</caption>
              <thead>
                <tr>
                  <th scope="col">Brief</th>
                  <th scope="col">Period covered</th>
                  <th scope="col">Status</th>
                  <th scope="col">Created</th>
                  <th scope="col">Approved on</th>
                </tr>
              </thead>
              <tbody>
                {reports.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link to={`/briefs/${r.id}`}>{r.title}</Link>
                    </td>
                    <td className="nowrap">
                      {fmtDate(r.period_start)} - {fmtDate(r.period_end)}
                    </td>
                    <td>
                      <StatusBadge status={r.status} />
                    </td>
                    <td>{fmtDateTime(r.created_at)}</td>
                    <td>{r.approved_at ? fmtDateTime(r.approved_at) : <span className="muted">Not yet</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </QueryView>
    </>
  );
}

function EditBrief({ report, onClose }: { report: ReportDetail; onClose: () => void }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const c = report.content;
  const [summary, setSummary] = useState(c.executive_summary ?? '');
  const [devs, setDevs] = useState((c.top_developments ?? []).map((d) => ({ ...d })));
  const [watch, setWatch] = useState((c.watch_items ?? []).join('\n'));
  const [reason, setReason] = useState('');
  const m = useMutation({
    mutationFn: () =>
      api.editReport(report.id, {
        executive_summary: summary,
        top_developments: devs,
        watch_items: watch.split('\n').map((s) => s.trim()).filter(Boolean),
        reason,
      }),
    onSuccess: () => {
      notify('Brief saved and sent for approval');
      void qc.invalidateQueries({ queryKey: ['report', report.id] });
      void qc.invalidateQueries({ queryKey: ['reports'] });
      onClose();
    },
  });
  return (
    <Modal
      open
      wide
      onClose={onClose}
      title="Edit brief"
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="brief-form" className="btn btn-primary" disabled={reason.trim().length < 3 || m.isPending}>
            Save edits
          </button>
        </>
      }
    >
      <form
        id="brief-form"
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          m.mutate();
        }}
      >
        <InlineError error={m.error} />
        <div className="field">
          <label htmlFor="eb-sum">Executive summary</label>
          <textarea id="eb-sum" rows={5} value={summary} onChange={(e) => setSummary(e.target.value)} />
        </div>
        <fieldset>
          <legend>Top developments</legend>
          <div className="stack">
            {devs.map((d, i) => (
              <div key={d.event_id} className="grid grid-2">
                <div className="field">
                  <label htmlFor={`eb-h-${i}`}>Headline {i + 1}</label>
                  <input id={`eb-h-${i}`} type="text" value={d.headline} onChange={(e) => setDevs(devs.map((x, j) => (j === i ? { ...x, headline: e.target.value } : x)))} />
                </div>
                <div className="field">
                  <label htmlFor={`eb-s-${i}`}>Why it matters (interpretation) {i + 1}</label>
                  <textarea id={`eb-s-${i}`} value={d.so_what} onChange={(e) => setDevs(devs.map((x, j) => (j === i ? { ...x, so_what: e.target.value } : x)))} />
                </div>
              </div>
            ))}
            {devs.length === 0 ? <span className="small muted">No top developments in this brief.</span> : null}
          </div>
        </fieldset>
        <div className="field">
          <label htmlFor="eb-watch">Things to keep an eye on (one per line)</label>
          <textarea id="eb-watch" rows={4} value={watch} onChange={(e) => setWatch(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="eb-reason">Why you are editing (required, kept in the activity log)</label>
          <input id="eb-reason" type="text" required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
      </form>
    </Modal>
  );
}

function BriefBody({ content }: { content: BriefContent }) {
  const s = content.sections ?? {};
  return (
    <div className="stack" style={{ gap: 16 }}>
      <section className="card" aria-labelledby="sum-h">
        <h2 id="sum-h">Executive summary</h2>
        <p style={{ whiteSpace: 'pre-wrap' }}>{content.executive_summary || 'No summary written yet.'}</p>
        {content.edited_by ? <span className="badge badge-human">Human-edited {content.edited_at ? fmtDateTime(content.edited_at) : ''}</span> : null}
      </section>
      <section className="card" aria-labelledby="top-h">
        <h2 id="top-h">Top developments</h2>
        {(content.top_developments ?? []).length === 0 ? <p className="muted">No important changes in this period.</p> : null}
        <ol className="stack" style={{ paddingLeft: 18 }}>
          {(content.top_developments ?? []).map((d) => {
            const digest = s.top?.find((t) => t.event_id === d.event_id);
            return (
              <li key={d.event_id} className="stack-sm">
                <div className="row">
                  {digest ? <BandBadge band={digest.band} score={digest.score} /> : null}
                  <Link to={`/events/${d.event_id}`} className="strong">
                    {d.headline}
                  </Link>
                </div>
                {digest?.facts?.slice(0, 3).map((f, i) => (
                  <StatementCard key={i} statement={{ section: 'fact', statement: f.statement, statement_type: 'FACT', confidence: 'Verified', evidence_ids: f.evidence_ids }} />
                ))}
                <StatementCard statement={{ section: 'so_what', statement: d.so_what, statement_type: 'INFERENCE', confidence: 'Medium', evidence_ids: [] }} />
                {digest?.unknowns?.slice(0, 1).map((u) => (
                  <StatementCard key={u} statement={{ section: 'unknown', statement: u, statement_type: 'UNKNOWN', confidence: 'Not applicable', evidence_ids: [] }} />
                ))}
              </li>
            );
          })}
        </ol>
      </section>
      <div className="grid grid-2">
        <section className="card" aria-labelledby="bcat-h">
          <h2 id="bcat-h">Upcoming milestones</h2>
          {(s.catalysts ?? []).length === 0 ? <p className="muted small">None expected in the next 90 days.</p> : null}
          <ul className="list-plain">
            {(s.catalysts ?? []).map((c) => (
              <li key={c.catalyst_id} className="stack-sm">
                <div className="row">
                  <strong>{catalystDate({ expected_date: c.expected_date, window_start: c.window?.[0] ?? null, window_end: c.window?.[1] ?? null })}</strong>
                  <BasisBadge basis={c.date_basis} />
                </div>
                <span className="small">
                  {c.title}
                  {c.asset ? ` (${c.asset})` : ''}
                </span>
              </li>
            ))}
          </ul>
        </section>
        <section className="card" aria-labelledby="watch-h">
          <h2 id="watch-h">Things to keep an eye on</h2>
          {(content.watch_items ?? []).length === 0 ? <p className="muted small">Nothing flagged.</p> : null}
          <ul className="small" style={{ paddingLeft: 18 }}>
            {(content.watch_items ?? []).map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </section>
        <section className="card" aria-labelledby="ne-h">
          <h2 id="ne-h">New competitors</h2>
          {(s.new_entrants ?? []).length === 0 ? <p className="muted small">No new competitors detected this period.</p> : null}
          <ul className="small" style={{ paddingLeft: 18 }}>
            {(s.new_entrants ?? []).map((e) => (
              <li key={e.event_id}>
                <Link to={`/events/${e.event_id}`}>{e.title}</Link>
              </li>
            ))}
          </ul>
        </section>
        <section className="card" aria-labelledby="rs-h">
          <h2 id="rs-h">Regulatory and scientific news</h2>
          {(s.regulatory_scientific ?? []).length === 0 ? <p className="muted small">Nothing this period.</p> : null}
          <ul className="small" style={{ paddingLeft: 18 }}>
            {(s.regulatory_scientific ?? []).map((e) => (
              <li key={e.event_id}>
                <span className="badge badge-neutral">{eventTypeLabel(e.type)}</span> <Link to={`/events/${e.event_id}`}>{e.title}</Link>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <section className="card" aria-labelledby="low-h">
        <h2 id="low-h">Lower-priority changes not shown above</h2>
        <p className="small">
          {s.low_materiality_summary?.count ?? 0} lower-priority change(s)
          {s.low_materiality_summary?.by_type && Object.keys(s.low_materiality_summary.by_type).length
            ? `: ${Object.entries(s.low_materiality_summary.by_type)
                .map(([k, v]) => `${eventTypeLabel(k)} (${v})`)
                .join(', ')}`
            : ''}
          . {s.low_materiality_summary?.note ?? ''} Total changes this period: {s.event_count ?? 0}.
        </p>
      </section>
      <p className="small muted">{content.disclaimer}</p>
      <p className="tiny muted">
        Drafted by AI {fmtDateTime(content.generated_at)} - {content.model_workflow_version}
      </p>
    </div>
  );
}

export function BriefDetailPage() {
  const { id = '' } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const { notify } = useToast();
  const q = useQuery({ queryKey: ['report', id], queryFn: () => api.report(id) });
  const [editing, setEditing] = useState(false);
  const [distOpen, setDistOpen] = useState(false);
  const [recipients, setRecipients] = useState('');
  const [showOriginal, setShowOriginal] = useState(false);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['report', id] });
    void qc.invalidateQueries({ queryKey: ['reports'] });
  };
  const approve = useMutation({
    mutationFn: () => api.approveReport(id),
    onSuccess: () => {
      notify('Brief approved');
      refresh();
    },
    onError: (e) => notify(e.message, 'error'),
  });
  const distribute = useMutation({
    mutationFn: () => api.distributeReport(id, recipients.split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean)),
    onSuccess: () => {
      notify('Brief queued for distribution');
      setDistOpen(false);
      refresh();
    },
  });
  if (q.isLoading) return <Loading label="Loading brief" />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  if (!q.data) return null;
  const r = q.data;
  const locked = r.status === 'approved' || r.status === 'distributed';
  return (
    <>
      <nav className="small" aria-label="Breadcrumb" style={{ marginBottom: 8 }}>
        <Link to="/briefs">
          <ArrowLeft size={13} aria-hidden /> All briefs
        </Link>
      </nav>
      <div className="page-header">
        <div>
          <h1>{r.content.title ?? r.title}</h1>
          <p>
            Covers {fmtDate(r.period_start)} - {fmtDate(r.period_end)}
            {r.approved_by ? ` - approved by ${shortId(r.approved_by)} ${fmtDateTime(r.approved_at)}` : ''}
            {r.distributed_at ? ` - sent ${fmtDateTime(r.distributed_at)} to ${r.distribution_list.join(', ')}` : ''}
          </p>
        </div>
        <ExportButtons label="Download brief" formats={['docx', 'pdf', 'pptx', 'md']} onExport={(f) => api.exportReport(id, f)} />
      </div>
      <div className="card row-between" style={{ marginBottom: 16 }}>
        <Stepper status={r.status} />
        <div className="btn-group">
          {can(PERMS.reportWrite) ? (
            <button
              type="button"
              className="btn"
              disabled={locked}
              onClick={() => setEditing(true)}
              title={locked ? 'Approved briefs are locked and cannot be edited' : 'Correct or reword the brief before approval'}
            >
              <PencilLine size={15} aria-hidden /> Edit brief
            </button>
          ) : null}
          {can(PERMS.reportApprove) ? (
            <>
              <button
                type="button"
                className="btn"
                disabled={locked || approve.isPending}
                onClick={() => approve.mutate()}
                title="Confirm the brief is accurate; it is then locked and can be sent"
              >
                <Check size={15} aria-hidden /> Approve brief
              </button>
              <button type="button" className="btn btn-primary" disabled={r.status !== 'approved'} onClick={() => setDistOpen(true)} title={r.status !== 'approved' ? 'Approve the brief before sending it' : 'Email the brief to recipients'}>
                <Send size={15} aria-hidden /> Send to recipients
              </button>
            </>
          ) : null}
          {r.original_content ? (
            <label className="checkbox">
              <input type="checkbox" checked={showOriginal} onChange={(e) => setShowOriginal(e.target.checked)} />
              Show original AI draft
            </label>
          ) : null}
        </div>
      </div>
      {showOriginal && r.original_content ? (
        <div className="banner banner-info" role="note">
          <p>Showing the original AI-written draft, before any analyst edits.</p>
        </div>
      ) : null}
      <BriefBody content={showOriginal && r.original_content ? r.original_content : r.content} />
      {editing ? <EditBrief report={r} onClose={() => setEditing(false)} /> : null}
      <Modal
        open={distOpen}
        onClose={() => setDistOpen(false)}
        title="Send brief to recipients"
        footer={
          <>
            <button type="button" className="btn" onClick={() => setDistOpen(false)}>
              Cancel
            </button>
            <button type="button" className="btn btn-primary" onClick={() => distribute.mutate()} disabled={!recipients.trim() || distribute.isPending}>
              Send
            </button>
          </>
        }
      >
        <div className="stack">
          <InlineError error={distribute.error} />
          <div className="field">
            <label htmlFor="dist">Email addresses (separate with commas)</label>
            <textarea id="dist" value={recipients} onChange={(e) => setRecipients(e.target.value)} data-autofocus />
          </div>
        </div>
      </Modal>
    </>
  );
}
