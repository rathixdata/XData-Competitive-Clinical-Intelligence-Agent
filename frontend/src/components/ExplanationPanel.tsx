import { Info, Scale, ShieldAlert, Sparkles } from 'lucide-react';
import type { AnswerExplanation, EventExplanation } from '../api/types';
import { closeness, dimensionName, humanizeEnum } from '../lib/labels';

/**
 * "Why am I seeing this?" - explainable-AI panel following NIST IR 8312:
 * Explanation, Meaningful (plain-language summary first), Explanation accuracy (computed from the
 * same values that produced the score), Knowledge limits (always shown).
 */
export function ExplanationPanel({ x }: { x: EventExplanation }) {
  const maxContribution = Math.max(...x.score.drivers.map((d) => d.contribution || 0), 1);
  return (
    <div className="stack-sm" data-testid="explanation-panel">
      <p style={{ margin: 0 }}>
        <Info size={14} aria-hidden /> <strong>In plain language:</strong> {x.summary}
      </p>

      <h3 style={{ margin: '8px 0 0' }}>What drove the importance score</h3>
      <p className="tiny muted" style={{ margin: 0 }}>{x.score.method}</p>
      <ul aria-label="Score drivers, largest first" style={{ listStyle: 'none', padding: 0, margin: 0 }} className="stack-sm">
        {x.score.drivers.map((d) => (
          <li key={d.dimension}>
            <div className="row-between small">
              <span>
                <strong>{d.name || dimensionName(d.dimension)}</strong>: rated {d.score.toFixed(0)}/100, weight {Math.round(d.weight * 100)}%
              </span>
              <span>+{d.contribution.toFixed(1)} pts</span>
            </div>
            <div aria-hidden className="driver-track">
              <div className="driver-fill" style={{ width: `${(100 * (d.contribution || 0)) / maxContribution}%` }} />
            </div>
            {d.reasons.length ? <div className="tiny muted">{d.reasons.join('; ')}</div> : null}
          </li>
        ))}
      </ul>

      {x.score.counterfactuals.length ? (
        <>
          <h3 style={{ margin: '8px 0 0' }}><Scale size={14} aria-hidden /> What would change the outcome</h3>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {x.score.counterfactuals.map((c) => <li key={c}>{c}</li>)}
            {x.score.sensitivity.slice(0, 2).map((s) => (
              <li key={s.dimension}>
                Without &ldquo;{x.score.drivers.find((d) => d.dimension === s.dimension)?.name ?? dimensionName(s.dimension)}&rdquo;, the score would be {s.score_if_zero.toFixed(0)}.
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {x.mapping.length ? (
        <>
          <h3 style={{ margin: '8px 0 0' }}>Why it is linked to your drug</h3>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {x.mapping.map((m) => (
              <li key={m.asset}>
                <strong>{m.asset}</strong> (how close: {closeness(m.proximity)}): has in common{' '}
                {Object.keys(m.shared_dimensions)
                  .map((k) => humanizeEnum(k).toLowerCase())
                  .join(', ') || 'nothing specific'}
                {m.path.length ? (
                  <div className="tiny muted">
                    Connection: {m.path.map((p) => p.replace(/competes_with/g, 'competes with').replace(/evaluated_in/g, 'is being tested in').replace(/_/g, ' ')).join('  ·  ')}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <h3 style={{ margin: '8px 0 0' }}><Sparkles size={14} aria-hidden /> How the text was produced</h3>
      <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
        <li>
          {x.generation.human_edited ? 'Edited by an analyst' : 'Written by AI'} ({x.generation.model ?? 'n/a'}, instructions version {x.generation.prompt_version ?? 'n/a'});{' '}
          {x.generation.review_status === 'Machine' ? 'not yet checked by an analyst' : `status: ${x.generation.review_status}`}.
        </li>
        <li>
          {x.evidence.facts_with_evidence}/{x.evidence.facts} verified facts cite retained source evidence;{' '}
          {x.evidence.supported} passed the automatic evidence check{x.evidence.withheld ? `; ${x.evidence.withheld} statement(s) that could not be verified were removed` : ''}
          {x.evidence.independent_judge_used ? ' (checked by a second AI and by fixed rules).' : ' (checked by fixed rules).'}
        </li>
      </ul>

      <KnowledgeLimits items={x.knowledge_limits} />
    </div>
  );
}

export function KnowledgeLimits({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <section aria-label="Knowledge limits" className="stack-sm">
      <h3 style={{ margin: '8px 0 0' }}><ShieldAlert size={14} aria-hidden /> What the system does not know</h3>
      <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
        {items.map((k) => <li key={k}>{k}</li>)}
      </ul>
    </section>
  );
}

export function AnswerTrace({ x }: { x: AnswerExplanation }) {
  return (
    <details data-testid="answer-trace">
      <summary className="small">
        <strong>How this answer was produced</strong>
      </summary>
      <ol className="small" style={{ margin: '6px 0 0', paddingLeft: 18 }}>
        {x.steps.map((s) => <li key={s}>{s}</li>)}
      </ol>
      <KnowledgeLimits items={x.knowledge_limits} />
    </details>
  );
}
