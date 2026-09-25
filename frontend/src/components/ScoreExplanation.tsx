import type { ScoreExplanation as SE } from '../api/types';

const DIM_NAMES: Record<string, string> = {
  R: 'Relevance (R)',
  C: 'Change significance (C)',
  P: 'Proximity to customer assets (P)',
  T: 'Timing (T)',
  N: 'Novelty (N)',
};
const ORDER = ['R', 'C', 'P', 'T', 'N'];

export function ScoreExplanation({ explanation, score }: { explanation: SE | null; score: number }) {
  if (!explanation?.dimensions) return <p className="muted">No score explanation recorded.</p>;
  const dims = Object.entries(explanation.dimensions).sort((a, b) => {
    const ia = ORDER.indexOf(a[0]);
    const ib = ORDER.indexOf(b[0]);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
  return (
    <div className="stack-sm">
      <p className="small muted" style={{ margin: 0 }}>
        Materiality {score.toFixed(1)} = weighted sum of dimensions{explanation.formula ? ` (${explanation.formula})` : ''}.
        {explanation.version ? ` Rules ${explanation.version}.` : ''}
      </p>
      <div className="table-wrap">
        <table className="table">
          <caption className="sr-only">Materiality score dimensions</caption>
          <thead>
            <tr>
              <th scope="col">Dimension</th>
              <th scope="col" className="num">
                Score
              </th>
              <th scope="col" className="num">
                Weight
              </th>
              <th scope="col" className="num">
                Contribution
              </th>
              <th scope="col">Rule hits</th>
            </tr>
          </thead>
          <tbody>
            {dims.map(([k, d]) => (
              <tr key={k}>
                <th scope="row" style={{ fontWeight: 500 }}>
                  {DIM_NAMES[k] ?? k}
                </th>
                <td className="num">
                  <div className="row" style={{ justifyContent: 'flex-end', flexWrap: 'nowrap' }}>
                    <div className="bar" style={{ width: 60 }} aria-hidden>
                      <span style={{ width: `${Math.min(100, d.score)}%` }} />
                    </div>
                    {d.score.toFixed(0)}
                  </div>
                </td>
                <td className="num">{d.weight.toFixed(2)}</td>
                <td className="num">{d.contribution.toFixed(1)}</td>
                <td>
                  {d.rule_hits.length ? (
                    <ul style={{ margin: 0, paddingLeft: 16 }}>
                      {d.rule_hits.map((h) => (
                        <li key={h}>{h}</li>
                      ))}
                    </ul>
                  ) : (
                    <span className="muted">none</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="kv small">
        {explanation.model_confidence ? (
          <>
            <dt>Model confidence</dt>
            <dd>{explanation.model_confidence}</dd>
          </>
        ) : null}
        {explanation.mapping_confidence !== undefined ? (
          <>
            <dt>Mapping confidence</dt>
            <dd>{explanation.mapping_confidence.toFixed(2)}</dd>
          </>
        ) : null}
        {explanation.proximity_rule ? (
          <>
            <dt>Proximity rule</dt>
            <dd>{explanation.proximity_rule}</dd>
          </>
        ) : null}
        {explanation.band_thresholds ? (
          <>
            <dt>Band thresholds</dt>
            <dd>
              {Object.entries(explanation.band_thresholds)
                .sort((a, b) => a[1] - b[1])
                .map(([b, v]) => `${b} >= ${v}`)
                .join(' | ')}
            </dd>
          </>
        ) : null}
      </dl>
    </div>
  );
}
