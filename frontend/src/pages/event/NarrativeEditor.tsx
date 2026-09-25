import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';
import { api } from '../../api/endpoints';
import { CONFIDENCES, STATEMENT_TYPES, type Artifact, type EvidenceLink, type Statement, type StatementType } from '../../api/types';
import { Modal } from '../../components/Dialog';
import { InlineError } from '../../components/States';
import { SECTION_LABELS, SECTION_ORDER, statementMeta } from '../../components/statementMeta';
import { useToast } from '../../lib/toastContext';
import { validateDraft } from '../../lib/narrative';

interface Draft extends Statement {
  key: number;
}

export function NarrativeEditor({ eventId, narrative, open, onClose }: { eventId: string; narrative: Artifact; open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const evidence: Record<string, EvidenceLink> = narrative.content.evidence ?? {};
  const evidenceIds = Object.keys(evidence).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const seq = useState(() => ({ n: 0 }))[0];
  const initial = (): Draft[] =>
    narrative.claims.map((c) => ({
      key: ++seq.n,
      section: c.section,
      statement: c.statement,
      statement_type: c.statement_type,
      confidence: c.confidence,
      evidence_ids: [...c.evidence_ids],
      affected_entity_ids: (c.affected_entity_ids ?? []).map(String),
    }));
  const [headline, setHeadline] = useState(narrative.content.headline ?? '');
  const [items, setItems] = useState<Draft[]>(initial);
  const [reason, setReason] = useState('');
  const [errors, setErrors] = useState<string[]>([]);
  const sections = Array.from(new Set([...SECTION_ORDER, ...items.map((i) => i.section)]));

  const save = useMutation({
    mutationFn: () =>
      api.editNarrative(eventId, {
        headline: headline || null,
        reason,
        statements: items.map(({ key: _key, ...s }) => ({
          section: s.section,
          statement: s.statement.trim(),
          statement_type: s.statement_type,
          confidence: s.confidence,
          evidence_ids: s.evidence_ids,
          affected_entity_ids: s.affected_entity_ids ?? [],
        })),
      }),
    onSuccess: () => {
      notify('Narrative saved as a new analyst-reviewed version');
      void qc.invalidateQueries({ queryKey: ['event', eventId] });
      onClose();
    },
  });

  const patch = (key: number, p: Partial<Draft>) => setItems((xs) => xs.map((x) => (x.key === key ? { ...x, ...p } : x)));

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title="Edit narrative"
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="narrative-form" className="btn btn-primary" disabled={save.isPending} aria-busy={save.isPending}>
            Save edited version
          </button>
        </>
      }
    >
      <form
        id="narrative-form"
        noValidate
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          const errs = validateDraft(items, reason, evidenceIds);
          setErrors(errs);
          if (errs.length === 0) save.mutate();
        }}
      >
        <p className="small muted">
          Edits create a new, human-edited version; the machine output and its evidence are retained unchanged. Verified facts may only cite evidence already
          retained for this event ({evidenceIds.join(', ') || 'none'}).
        </p>
        {errors.length ? (
          <div className="banner banner-danger" role="alert">
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <InlineError error={save.error} />
        <div className="field">
          <label htmlFor="ne-headline">Headline</label>
          <input id="ne-headline" type="text" value={headline} onChange={(e) => setHeadline(e.target.value)} />
        </div>
        <ol className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {items.map((s, i) => {
            const meta = statementMeta(s.statement_type);
            return (
              <li key={s.key} className={`stmt ${meta.className}`}>
                <fieldset style={{ border: 0, padding: 0 }}>
                  <legend className="sr-only">Statement {i + 1}</legend>
                  <div className="form-grid">
                    <div className="field">
                      <label htmlFor={`ne-type-${s.key}`}>Statement type</label>
                      <select
                        id={`ne-type-${s.key}`}
                        value={s.statement_type}
                        onChange={(e) => {
                          const t = e.target.value as StatementType;
                          patch(s.key, { statement_type: t, confidence: t === 'FACT' ? 'Verified' : t === 'INFERENCE' ? 'Medium' : 'Not applicable' });
                        }}
                      >
                        {STATEMENT_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {statementMeta(t).label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="field">
                      <label htmlFor={`ne-sec-${s.key}`}>Section</label>
                      <select id={`ne-sec-${s.key}`} value={s.section} onChange={(e) => patch(s.key, { section: e.target.value })}>
                        {sections.map((x) => (
                          <option key={x} value={x}>
                            {SECTION_LABELS[x] ?? x}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="field">
                      <label htmlFor={`ne-conf-${s.key}`}>Confidence</label>
                      <select id={`ne-conf-${s.key}`} value={s.confidence} onChange={(e) => patch(s.key, { confidence: e.target.value })}>
                        {CONFIDENCES.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="field">
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => setItems((xs) => xs.filter((x) => x.key !== s.key))}
                        aria-label={`Remove statement ${i + 1}`}
                      >
                        <Trash2 size={14} aria-hidden /> Remove
                      </button>
                    </div>
                  </div>
                  <div className="field" style={{ marginTop: 8 }}>
                    <label htmlFor={`ne-text-${s.key}`}>Statement {i + 1} text</label>
                    <textarea id={`ne-text-${s.key}`} value={s.statement} onChange={(e) => patch(s.key, { statement: e.target.value })} />
                  </div>
                  <fieldset style={{ marginTop: 8 }}>
                    <legend>Cited evidence {s.statement_type === 'FACT' ? '(required for Verified fact)' : '(optional)'}</legend>
                    <div className="row">
                      {evidenceIds.length === 0 ? <span className="small muted">No retained evidence</span> : null}
                      {evidenceIds.map((id) => (
                        <label key={id} className="checkbox" title={evidence[id]?.excerpt ?? ''}>
                          <input
                            type="checkbox"
                            checked={s.evidence_ids.includes(id)}
                            onChange={(e) =>
                              patch(s.key, { evidence_ids: e.target.checked ? [...s.evidence_ids, id] : s.evidence_ids.filter((x) => x !== id) })
                            }
                          />
                          {id}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                </fieldset>
              </li>
            );
          })}
        </ol>
        <div>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() =>
              setItems((xs) => [
                ...xs,
                { key: ++seq.n, section: 'why_it_may_matter', statement: '', statement_type: 'INFERENCE', confidence: 'Medium', evidence_ids: [], affected_entity_ids: [] },
              ])
            }
          >
            <Plus size={14} aria-hidden /> Add statement
          </button>
        </div>
        <div className="field">
          <label htmlFor="ne-reason">Reason for edit (required, audited)</label>
          <textarea id="ne-reason" required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
      </form>
    </Modal>
  );
}
