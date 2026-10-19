import type { ScoreExplanation as SE } from '../api/types';
import { DIMENSION_LABELS, closeness, dimensionName } from '../lib/labels';

const ORDER = ['R', 'C', 'P', 'T', 'N'];

export function ScoreExplanation({ explanation, score }: { explanation: SE | null; score: number }) {
  if (!explanation?.dimensions) return <p className="muted">No score breakdown was recorded for this change.</p>;
  const dims = Object.entries(explanation.dimensions).sort((a, b) => {
    const ia = ORDER.indexOf(a[0]);
    const ib = ORDER.indexOf(b[0]);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
  return (
    <div className="stack-sm">
      <p className="small" style={{ margin: 0 }}>
        The importance score of <strong>{score.toFixed(0)}/100</strong> adds up five factors. Each factor is rated 0-100 and weighted; the points below show how much each one
        contributed.
      </p>
      <ul className="factor-list" aria-label="Importance score factors">
        {dims.map(([k, d]) => (
          <li key={k}>
            <div className="row-between" style={{ flexWrap: 'nowrap', alignItems: 'baseline' }}>
              <span className="strong" title={DIMENSION_LABELS[k]?.description}>
                {dimensionName(k)}
              </span>
              <span className="nowrap small">
                <strong>+{d.contribution.toFixed(1)}</strong> pts
              </span>
            </div>
            <div className="row" style={{ flexWrap: 'nowrap', gap: 8 }}>
              <div className="bar" style={{ flex: 1 }} aria-hidden>
                <span style={{ width: `${Math.min(100, d.score)}%` }} />
              </div>
              <span className="tiny muted nowrap">
                rated {d.score.toFixed(0)}/100 - weight {Math.round(d.weight * 100)}%
              </span>
            </div>
            {d.rule_hits.length ? <div className="tiny muted">Why: {d.rule_hits.map((h) => h.replace(/_/g, ' ')).join('; ')}</div> : null}
          </li>
        ))}
      </ul>
      <details className="tech-details">
        <summary className="small">Technical details</summary>
        <dl className="kv small" style={{ marginTop: 6 }}>
          {explanation.formula ? (
            <>
              <dt>Formula</dt>
              <dd className="mono">{explanation.formula}</dd>
            </>
          ) : null}
          {explanation.version ? (
            <>
              <dt>Scoring rules version</dt>
              <dd>{explanation.version}</dd>
            </>
          ) : null}
          <dt>Factor codes</dt>
          <dd>{ORDER.map((c) => `${c} = ${dimensionName(c)}`).join('; ')}</dd>
          {explanation.model_confidence ? (
            <>
              <dt>Scoring confidence</dt>
              <dd>{explanation.model_confidence}</dd>
            </>
          ) : null}
          {explanation.mapping_confidence !== undefined ? (
            <>
              <dt>Confidence in the link to your drug</dt>
              <dd>{closeness(explanation.mapping_confidence)}</dd>
            </>
          ) : null}
          {explanation.proximity_rule ? (
            <>
              <dt>Similarity rule</dt>
              <dd>{explanation.proximity_rule}</dd>
            </>
          ) : null}
          {explanation.band_thresholds ? (
            <>
              <dt>Priority thresholds</dt>
              <dd>
                {Object.entries(explanation.band_thresholds)
                  .sort((a, b) => b[1] - a[1])
                  .map(([b, v]) => `${b} from ${v}`)
                  .join(' | ')}
              </dd>
            </>
          ) : null}
        </dl>
      </details>
    </div>
  );
}
