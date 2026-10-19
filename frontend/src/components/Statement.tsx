import { FileSearch } from 'lucide-react';
import type { EvidenceLink, Statement } from '../api/types';
import { STATEMENT_META, statementMeta } from './statementMeta';
import { ConfidenceBadge } from './Badges';

interface Props {
  statement: Statement;
  evidence?: Record<string, EvidenceLink>;
  onOpenEvidence?: (link: EvidenceLink) => void;
  reviewStatus?: string;
}

function validationText(s: Statement): string | null {
  const v = s.validation_status;
  if (!v || v === 'not_applicable') return null;
  if (v === 'supported') return 'Evidence check: supported';
  if (v === 'partially_supported') return 'Evidence check: partially supported';
  if (v === 'unsupported') return 'Evidence check: not supported';
  if (v === 'analyst_asserted') return 'Stated by an analyst';
  return `Evidence check: ${v.replace(/_/g, ' ')}`;
}

export function StatementLabel({ type }: { type: string }) {
  const meta = statementMeta(type);
  const Icon = meta.icon;
  return (
    <span className="stmt-label" title={meta.description}>
      <Icon size={14} aria-hidden />
      {meta.label}
      <span className="sr-only"> - {meta.description}</span>
    </span>
  );
}

/** One typed statement. Facts, interpretations, unknowns and investigations are never styled alike. */
export function StatementCard({ statement, evidence, onOpenEvidence, reviewStatus }: Props) {
  const meta = statementMeta(statement.statement_type);
  const vt = validationText(statement);
  const isFact = statement.statement_type === 'FACT';
  return (
    <article className={`stmt ${meta.className}`} aria-label={`${meta.label}: ${statement.statement}`} data-statement-type={statement.statement_type}>
      <div className="stmt-head">
        <StatementLabel type={statement.statement_type} />
        {statement.confidence && statement.confidence !== 'Not applicable' ? <ConfidenceBadge confidence={statement.confidence} /> : null}
        {reviewStatus && reviewStatus !== 'Machine' ? <span className="badge badge-human">{reviewStatus}</span> : null}
      </div>
      <p className="stmt-text">{statement.statement}</p>
      <div className="stmt-meta">
        {vt ? <span title="Automatic check that the cited source really says this">{vt}</span> : null}
        {statement.original_statement_type && statement.original_statement_type !== statement.statement_type ? (
          <span>(re-typed from {statementMeta(statement.original_statement_type).label} by validator)</span>
        ) : null}
        {statement.evidence_ids.length > 0 ? (
          <span className="row" style={{ gap: 4 }}>
            <span>{isFact ? 'Evidence:' : 'Based on:'}</span>
            {statement.evidence_ids.map((id) => {
              const link = evidence?.[id];
              if (!onOpenEvidence) {
                return (
                  <span key={id} className="badge badge-neutral" title="Source reference (open the change to see the source)">
                    {id}
                  </span>
                );
              }
              return (
                <button
                  key={id}
                  type="button"
                  className="chip"
                  disabled={!link}
                  onClick={() => link && onOpenEvidence(link)}
                  aria-label={`Open evidence ${id}${link?.title ? `: ${link.title}` : ''}`}
                  title="Show the source passage behind this statement"
                >
                  <FileSearch size={12} aria-hidden />
                  {id}
                </button>
              );
            })}
          </span>
        ) : isFact ? (
          <span className="badge badge-danger" title="This fact does not cite a source; treat it with caution">No evidence cited</span>
        ) : null}
      </div>
    </article>
  );
}

export function StatementLegend() {
  return (
    <div className="legend" role="note" aria-label="How to read these statements">
      <span className="strong">How to read this:</span>
      {Object.entries(STATEMENT_META).map(([k, m]) => {
        const Icon = m.icon;
        return (
          <span key={k} className="stmt-label" title={m.description} style={{ color: `var(--${k === 'FACT' ? 'fact' : k === 'INFERENCE' ? 'infer' : k === 'UNKNOWN' ? 'unknown' : 'invest'}-fg)` }}>
            <Icon size={13} aria-hidden /> {m.label}
            <span className="sr-only"> - {m.description}</span>
          </span>
        );
      })}
    </div>
  );
}
