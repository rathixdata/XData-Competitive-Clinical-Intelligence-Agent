import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AnswerTrace, ExplanationPanel } from './ExplanationPanel';
import type { EventExplanation } from '../api/types';

const x: EventExplanation = {
  principles: ['explanation', 'meaningful', 'explanation_accuracy', 'knowledge_limits'],
  summary: 'Scored 93/100 (Executive Alert). It maps to XD-101.',
  score: {
    method: 'Deterministic rule-based scoring',
    magnitude_gate: 1,
    drivers: [{ dimension: 'C', name: 'Size of the change', score: 100, weight: 0.25, contribution: 25, reasons: ['primary endpoint replaced'] }],
    sensitivity: [{ dimension: 'C', score_if_zero: 68, delta: 25 }],
    counterfactuals: ['It would drop out of Executive Alert if the score fell by 8.3 points.'],
  },
  mapping: [{ asset: 'XD-101', proximity: 1, rationale: 'r', path: ['XD-101 —competes_with→ CA-201'], shared_dimensions: { target: { weight: 0.3, score: 1 } } }],
  evidence: { facts: 3, facts_with_evidence: 3, supported: 3, withheld: 0, independent_judge_used: false },
  generation: { ai_generated: true, human_edited: false, review_status: 'Machine', model: 'claude-opus-5', workflow: 'w', prompt_version: '1.0.0', generation_id: null },
  knowledge_limits: ['Confidence labels are policy-based, not calibrated probabilities.'],
};

describe('ExplanationPanel', () => {
  it('renders plain-language summary, drivers, counterfactuals and knowledge limits', () => {
    render(<ExplanationPanel x={x} />);
    expect(screen.getByText(/In plain language/)).toBeInTheDocument();
    expect(screen.getByText(/primary endpoint replaced/)).toBeInTheDocument();
    expect(screen.getByText(/would drop out of Executive Alert/)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Knowledge limits' })).toBeInTheDocument();
    expect(screen.getByText(/3\/3 verified facts cite retained source evidence/)).toBeInTheDocument();
  });

  it('renders the answer trace', () => {
    render(<AnswerTrace x={{ principles: [], steps: ['Retrieved 2 records'], knowledge_limits: ['limit'], evidence_coverage: { facts: 1, facts_with_evidence: 1 } }} />);
    expect(screen.getByText('Retrieved 2 records')).toBeInTheDocument();
  });
});
