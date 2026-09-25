import { CheckCircle2, HelpCircle, Search, Sparkles, type LucideIcon } from 'lucide-react';
import type { StatementType } from '../api/types';

export interface StatementMeta {
  label: string;
  short: string;
  className: string;
  icon: LucideIcon;
  description: string;
}

/** SRS 13.1 visual semantics: each statement type has a distinct label, icon and treatment. */
export const STATEMENT_META: Record<StatementType, StatementMeta> = {
  FACT: {
    label: 'Verified fact',
    short: 'Fact',
    className: 'stmt-fact',
    icon: CheckCircle2,
    description: 'Directly supported by cited source evidence.',
  },
  INFERENCE: {
    label: 'AI interpretation',
    short: 'Interpretation',
    className: 'stmt-inference',
    icon: Sparkles,
    description: 'AI-generated hypothesis; not an established fact.',
  },
  UNKNOWN: {
    label: 'Unknown',
    short: 'Unknown',
    className: 'stmt-unknown',
    icon: HelpCircle,
    description: 'Not established by the available evidence.',
  },
  RECOMMENDED_INVESTIGATION: {
    label: 'Recommended investigation',
    short: 'Investigate',
    className: 'stmt-investigation',
    icon: Search,
    description: 'Suggested follow-up to close an evidence gap.',
  },
};

export function statementMeta(t: string): StatementMeta {
  return STATEMENT_META[t as StatementType] ?? STATEMENT_META.UNKNOWN;
}

export const SECTION_LABELS: Record<string, string> = {
  what_changed: 'What changed',
  affected_assets: 'Affected assets',
  why_it_may_matter: 'Why it may matter',
  known_limitations: 'Known limitations',
  recommended_investigation: 'Recommended investigation',
  answer: 'Answer',
  interpretation: 'Interpretation',
  limitations: 'Limitations',
};

export const SECTION_ORDER = ['what_changed', 'affected_assets', 'why_it_may_matter', 'known_limitations', 'recommended_investigation'];
