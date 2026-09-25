import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/endpoints';
import { FEEDBACK_LABELS, type EventDetail, type FeedbackLabel } from '../../api/types';
import { PERMS, useAuth } from '../../auth/context';
import { InlineError } from '../../components/States';
import { fmtDateTime } from '../../lib/format';
import { useToast } from '../../lib/toastContext';

const FEEDBACK_TEXT: Record<FeedbackLabel, string> = {
  USEFUL: 'Useful',
  NOT_USEFUL: 'Not useful',
  MATERIAL: 'Material',
  NOT_MATERIAL: 'Not material',
  WRONG_MAPPING: 'Wrong asset mapping',
  INCORRECT_INTERPRETATION: 'Incorrect interpretation',
  ALREADY_KNOWN: 'Already known',
  ESCALATE: 'Escalate',
};

export function FeedbackPanel({ detail }: { detail: EventDetail }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const { notify } = useToast();
  const [label, setLabel] = useState<FeedbackLabel | null>(null);
  const [reason, setReason] = useState('');
  const [comment, setComment] = useState('');
  const m = useMutation({
    mutationFn: () =>
      api.feedback({ intel_event_id: detail.event.id, label: label as FeedbackLabel, reason: reason || undefined, comment: comment || undefined }),
    onSuccess: () => {
      notify('Feedback recorded - thank you');
      setLabel(null);
      setReason('');
      setComment('');
      void qc.invalidateQueries({ queryKey: ['event', detail.event.id] });
    },
  });
  const counts = detail.feedback.counts;
  return (
    <div className="stack">
      {Object.keys(counts).length ? (
        <p className="small" style={{ margin: 0 }}>
          Team feedback:{' '}
          {Object.entries(counts)
            .map(([k, v]) => `${FEEDBACK_TEXT[k as FeedbackLabel] ?? k} (${v})`)
            .join(', ')}
        </p>
      ) : (
        <p className="small muted" style={{ margin: 0 }}>
          No feedback yet.
        </p>
      )}
      {can(PERMS.feedbackWrite) ? (
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            if (label) m.mutate();
          }}
        >
          <fieldset>
            <legend>How would you rate this intelligence?</legend>
            <div className="row" style={{ gap: 6 }}>
              {FEEDBACK_LABELS.map((l) => (
                <button key={l} type="button" className={`btn btn-sm ${label === l ? 'btn-primary' : ''}`} aria-pressed={label === l} onClick={() => setLabel(label === l ? null : l)}>
                  {FEEDBACK_TEXT[l]}
                </button>
              ))}
            </div>
          </fieldset>
          {label ? (
            <>
              <div className="field">
                <label htmlFor="fb-reason">Reason (optional)</label>
                <input id="fb-reason" type="text" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="fb-comment">Comment (optional)</label>
                <textarea id="fb-comment" maxLength={4000} value={comment} onChange={(e) => setComment(e.target.value)} />
              </div>
              {label === 'ESCALATE' ? <p className="small muted">Escalate feedback also marks the event as escalated.</p> : null}
            </>
          ) : null}
          <InlineError error={m.error} />
          <div>
            <button type="submit" className="btn btn-primary btn-sm" disabled={!label || m.isPending}>
              Submit feedback
            </button>
          </div>
        </form>
      ) : null}
      {detail.feedback.mine.length ? (
        <div>
          <h3 className="small">Your feedback</h3>
          <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
            {detail.feedback.mine.map((f) => (
              <li key={f.id}>
                {FEEDBACK_TEXT[f.label] ?? f.label} - {fmtDateTime(f.created_at)}
                {f.reason ? ` - ${f.reason}` : ''}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
