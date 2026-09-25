import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, BookOpenCheck, CircleSlash, Loader2, MessageSquarePlus, Send } from 'lucide-react';
import { api } from '../api/endpoints';
import { askStream } from '../api/sse';
import type { AskAnswer, AskProgress, AskStage, EvidenceLink } from '../api/types';
import { ConfidenceBadge } from '../components/Badges';
import { Drawer } from '../components/Dialog';
import { EvidenceDrawer } from '../components/EvidenceDrawer';
import { ExportButtons } from '../components/ExportButtons';
import { StatementCard, StatementLegend } from '../components/Statement';
import { ErrorState, Loading } from '../components/States';
import { useLandscape } from '../state/landscapeContext';
import { fmtDateTime, fmtRelative } from '../lib/format';
import { errorMessage } from '../lib/toastContext';
import { AnswerTrace } from '../components/ExplanationPanel';

type AnswerContent = Omit<AskAnswer, 'session_id' | 'turn_id' | 'artifact_id'>;

interface Turn {
  key: string;
  question: string;
  artifactId: string | null;
  answer: AnswerContent | null;
  error?: string;
  progress?: AskProgress[];
  pending?: boolean;
}

const STAGES: { id: AskStage; label: string }[] = [
  { id: 'planned', label: 'Planning' },
  { id: 'retrieved', label: 'Retrieving evidence' },
  { id: 'generated', label: 'Generating' },
  { id: 'validated', label: 'Validating against evidence' },
];

const SUGGESTIONS = ['What changed this week?', 'Which competitor trials changed their primary endpoint?', 'Compare CA-201 and BRV-310', 'What catalysts are expected in the next 6 months?'];

function stageDetail(p: AskProgress): string {
  if (p.stage === 'retrieved') return `${String(p.passages ?? 0)} passages, ${String(p.changes ?? 0)} changes, ${String(p.structured ?? 0)} records`;
  if (p.stage === 'validated' && p.counts && typeof p.counts === 'object') {
    const c = p.counts as Record<string, number>;
    return `${c.supported ?? 0} supported, ${c.unsupported ?? 0} unsupported`;
  }
  if (p.stage === 'generated' && p.model) return String(p.model);
  return '';
}

function ProgressSteps({ progress, pending }: { progress: AskProgress[]; pending: boolean }) {
  const done = new Set(progress.map((p) => p.stage));
  const firstOpen = STAGES.find((s) => !done.has(s.id))?.id;
  return (
    <ol className="progress-steps" aria-label="Answer progress">
      {STAGES.map((s) => {
        const p = progress.find((x) => x.stage === s.id);
        const state = p ? 'done' : pending && s.id === firstOpen ? 'active' : '';
        return (
          <li key={s.id} className={state}>
            {state === 'active' ? <Loader2 size={12} className="spin" aria-hidden /> : null}
            {s.label}
            {p ? `: ${stageDetail(p) || 'done'}` : state === 'active' ? '...' : ''}
          </li>
        );
      })}
    </ol>
  );
}

function AnswerView({ answer, artifactId, onOpenEvidence }: { answer: AnswerContent; artifactId: string | null; onOpenEvidence: (l: EvidenceLink) => void }) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const facts = answer.statements.filter((s) => s.statement_type === 'FACT');
  const other = answer.statements.filter((s) => s.statement_type !== 'FACT');
  const evidence = Object.values(answer.evidence ?? {});
  return (
    <article className="card stack" aria-label="Answer">
      {answer.abstained ? (
        <div className="banner banner-warning" role="note">
          <CircleSlash size={18} aria-hidden />
          <p>
            <strong>Abstained:</strong> the retained evidence was insufficient for a verified answer. Nothing below should be read as a finding.
          </p>
        </div>
      ) : null}
      {answer.comparison_warning ? (
        <div className="banner banner-indirect" role="note">
          <AlertTriangle size={18} aria-hidden />
          <p>
            <strong>Indirect comparison:</strong> {answer.comparison_warning}
          </p>
        </div>
      ) : null}
      <section aria-label="Answer summary" className="stack-sm">
        <div className="row-between">
          <h3 style={{ margin: 0 }}>Answer</h3>
          <ConfidenceBadge confidence={answer.confidence} />
        </div>
        <p style={{ margin: 0 }}>{answer.answer}</p>
      </section>
      {facts.length ? (
        <section aria-label="Evidence" className="stack-sm">
          <h3 style={{ margin: 0 }}>Evidence</h3>
          <StatementLegend />
          {facts.map((s, i) => (
            <StatementCard key={i} statement={s} evidence={answer.evidence} onOpenEvidence={onOpenEvidence} />
          ))}
        </section>
      ) : null}
      {other.length ? (
        <section aria-label="Interpretation and unknowns" className="stack-sm">
          <h3 style={{ margin: 0 }}>Interpretation, unknowns and follow-ups</h3>
          {other.map((s, i) => (
            <StatementCard key={i} statement={s} evidence={answer.evidence} onOpenEvidence={onOpenEvidence} />
          ))}
        </section>
      ) : null}
      {answer.limitations?.length ? (
        <section aria-label="Limitations">
          <h3>Limitations</h3>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {answer.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {answer.explanation ? <AnswerTrace x={answer.explanation} /> : null}
      <div className="row-between">
        <div className="row">
          <button type="button" className="btn btn-sm" onClick={() => setSourcesOpen(true)} disabled={evidence.length === 0}>
            <BookOpenCheck size={14} aria-hidden /> Sources ({answer.sources?.length ?? 0})
          </button>
          <span className="tiny muted">
            {answer.model_workflow_version} - {fmtDateTime(answer.generated_at)}
          </span>
        </div>
        {artifactId ? <ExportButtons label="Export answer" onExport={(f) => api.askExport(artifactId, f)} /> : null}
      </div>
      <Drawer open={sourcesOpen} onClose={() => setSourcesOpen(false)} title="Sources">
        <ul className="list-plain">
          {evidence.map((e) => (
            <li key={e.evidence_id} className="stack-sm">
              <div className="row">
                <span className="badge badge-neutral">{e.evidence_id}</span>
                <strong>{e.title ?? e.source_type}</strong>
              </div>
              <span className="small muted">
                {e.source_type} - retrieved {fmtDateTime(e.retrieved_at)}
              </span>
              <button
                type="button"
                className="btn btn-sm"
                style={{ alignSelf: 'flex-start' }}
                onClick={() => {
                  setSourcesOpen(false);
                  onOpenEvidence(e);
                }}
              >
                Open evidence
              </button>
            </li>
          ))}
        </ul>
      </Drawer>
    </article>
  );
}

export function AskPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { landscapeId } = useLandscape();
  const sessions = useQuery({ queryKey: ['ask-sessions'], queryFn: api.askSessions });
  const session = useQuery({ queryKey: ['ask-session', sessionId], queryFn: () => api.askSession(sessionId as string), enabled: Boolean(sessionId) });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState('');
  const [evidence, setEvidence] = useState<EvidenceLink | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const prevSession = useRef<string | undefined>(sessionId);
  const assignedSession = useRef<string | null>(null);

  // Switching to another conversation clears the thread; a session id assigned by our own
  // first answer keeps the in-flight thread (and its streamed progress).
  useEffect(() => {
    if (prevSession.current === sessionId) return;
    prevSession.current = sessionId;
    if (assignedSession.current !== sessionId) setTurns([]);
    assignedSession.current = null;
  }, [sessionId]);
  useEffect(() => {
    if (session.data && !busy) {
      const turnsData = session.data.turns;
      // Keep locally streamed progress for turns we just asked (by turn id).
      setTurns((prev) =>
        
        turnsData.map((t) => ({
          key: t.turn_id,
          question: t.question,
          artifactId: t.artifact_id,
          answer: t.answer,
          progress: prev.find((p) => p.key === t.turn_id)?.progress,
        })),
      );
    }
  }, [session.data, busy]);
  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end', behavior: 'smooth' });
  }, [turns.length]);

  const ask = async (text: string) => {
    const q = text.trim();
    if (q.length < 3 || busy) return;
    const key = `local-${Date.now()}`;
    setTurns((t) => [...t, { key, question: q, artifactId: null, answer: null, pending: true, progress: [] }]);
    setQuestion('');
    setBusy(true);
    setLive('Question sent. Planning...');
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const out = await askStream(
        { question: q, session_id: sessionId ?? null, landscape_id: landscapeId ?? null },
        {
          signal: ctrl.signal,
          onProgress: (p) => {
            setTurns((ts) => ts.map((t) => (t.key === key ? { ...t, progress: [...(t.progress ?? []), p] } : t)));
            setLive(`${STAGES.find((s) => s.id === p.stage)?.label ?? p.stage} complete.`);
          },
        },
      );
      const { session_id, turn_id, artifact_id, ...content } = out;
      setTurns((ts) => ts.map((t) => (t.key === key ? { ...t, key: turn_id, pending: false, artifactId: artifact_id, answer: content } : t)));
      setLive(out.abstained ? 'Answer ready: the assistant abstained due to insufficient evidence.' : `Answer ready. ${out.answer}`);
      void qc.invalidateQueries({ queryKey: ['ask-sessions'] });
      if (session_id !== sessionId) {
        assignedSession.current = session_id;
        navigate(`/ask/${session_id}`, { replace: !sessionId });
      } else {
        void qc.invalidateQueries({ queryKey: ['ask-session', session_id] });
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        setTurns((ts) => ts.map((t) => (t.key === key ? { ...t, pending: false, error: 'Cancelled.' } : t)));
        setLive('Cancelled.');
      } else {
        setTurns((ts) => ts.map((t) => (t.key === key ? { ...t, pending: false, error: errorMessage(e) } : t)));
        setLive(`Error: ${errorMessage(e)}`);
      }
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void ask(question);
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Ask the landscape</h1>
          <p>Grounded answers from retained evidence. Follow-up questions keep the conversation context.</p>
        </div>
        <Link to="/ask" className="btn" onClick={() => setTurns([])}>
          <MessageSquarePlus size={15} aria-hidden /> New conversation
        </Link>
      </div>
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {live}
      </div>
      <div className="ask-grid">
        <section aria-label="Conversation" className="stack" style={{ minWidth: 0 }}>
          {sessionId && session.isLoading ? <Loading label="Loading conversation" /> : null}
          {session.error ? <ErrorState error={session.error} /> : null}
          {turns.length === 0 && !session.isLoading ? (
            <div className="card stack-sm">
              <h2>Try asking</h2>
              <div className="row">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" className="btn btn-sm btn-wrap" onClick={() => void ask(s)} disabled={busy}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <div className="thread" aria-busy={busy}>
            {turns.map((t) => (
              <div key={t.key} className="stack-sm">
                <div className="bubble-q">
                  <span className="sr-only">You asked: </span>
                  {t.question}
                </div>
                {t.pending || (t.progress && t.progress.length > 0) ? <ProgressSteps progress={t.progress ?? []} pending={Boolean(t.pending)} /> : null}
                {t.error ? (
                  <div className="banner banner-danger" role="alert">
                    <p>{t.error}</p>
                  </div>
                ) : null}
                {t.answer ? <AnswerView answer={t.answer} artifactId={t.artifactId} onOpenEvidence={setEvidence} /> : null}
              </div>
            ))}
          </div>
          <div ref={endRef} />
          <form className="composer" onSubmit={submit}>
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="ask-q" className="sr-only">
                Your question
              </label>
              <textarea
                id="ask-q"
                value={question}
                placeholder="Ask about competitors, trials, endpoints, timelines..."
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    void ask(question);
                  }
                }}
                maxLength={2000}
              />
            </div>
            {busy ? (
              <button type="button" className="btn" onClick={() => abortRef.current?.abort()}>
                Cancel
              </button>
            ) : null}
            <button type="submit" className="btn btn-primary" disabled={busy || question.trim().length < 3}>
              <Send size={15} aria-hidden /> Ask
            </button>
          </form>
        </section>
        <aside aria-label="Previous conversations" className="card hide-sm" style={{ alignSelf: 'start' }}>
          <h2>Conversations</h2>
          {sessions.isLoading ? <Loading /> : null}
          {sessions.data?.length === 0 ? <p className="small muted">No previous conversations.</p> : null}
          <ul className="list-plain">
            {(sessions.data ?? []).map((s) => (
              <li key={s.id}>
                <Link to={`/ask/${s.id}`} aria-current={s.id === sessionId ? 'page' : undefined} className={s.id === sessionId ? 'strong' : undefined}>
                  {s.title || 'Untitled conversation'}
                </Link>
                <div className="tiny muted">{fmtRelative(s.updated_at)}</div>
              </li>
            ))}
          </ul>
        </aside>
      </div>
      <EvidenceDrawer link={evidence} onClose={() => setEvidence(null)} />
    </>
  );
}
