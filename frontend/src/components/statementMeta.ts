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
    description: 'Verified fact: stated directly in a cited source record. Click the evidence chip to see it.',
  },
  INFERENCE: {
    label: 'AI interpretation',
    short: 'Interpretation',
    className: 'stmt-inference',
    icon: Sparkles,
    description: 'AI interpretation (hypothesis): what this might mean for you. Useful for thinking, but not an established fact.',
  },
  UNKNOWN: {
    label: 'Unknown',
    short: 'Unknown',
    className: 'stmt-unknown',
    icon: HelpCircle,
    description: 'Not known yet: the available sources do not answer this.',
  },
  RECOMMENDED_INVESTIGATION: {
    label: 'Suggested next step',
    short: 'Next step',
    className: 'stmt-investigation',
    icon: Search,
    description: 'Suggested next step: something worth checking to fill a gap in the evidence.',
  },
};

export function statementMeta(t: string): StatementMeta {
  return STATEMENT_META[t as StatementType] ?? STATEMENT_META.UNKNOWN;
}

export const SECTION_LABELS: Record<string, string> = {
  what_changed: 'What changed',
  affected_assets: 'Which of your drugs it affects',
  why_it_may_matter: 'Why it may matter to you',
  known_limitations: 'What we do not know yet',
  recommended_investigation: 'Suggested next steps',
  answer: 'Answer',
  interpretation: 'What it may mean',
  limitations: 'Limitations',
};

export const SECTION_ORDER = ['what_changed', 'affected_assets', 'why_it_may_matter', 'known_limitations', 'recommended_investigation'];
