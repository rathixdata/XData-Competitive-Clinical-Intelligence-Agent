import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StatementCard } from './Statement';
import type { EvidenceLink, Statement } from '../api/types';

const evidence: Record<string, EvidenceLink> = {
  S1: { evidence_id: 'S1', kind: 'structured_field', title: 'ZEPHYR-3 record', uri: 'https://clinicaltrials.gov/study/NCT99000001' },
};

const fact: Statement = {
  section: 'what_changed',
  statement: 'Enrollment changed from 320 to 480.',
  statement_type: 'FACT',
  confidence: 'Verified',
  evidence_ids: ['S1'],
  validation_status: 'supported',
};
const inference: Statement = {
  section: 'why_it_may_matter',
  statement: 'A larger enrollment target may reflect revised powering assumptions.',
  statement_type: 'INFERENCE',
  confidence: 'Medium',
  evidence_ids: ['S1'],
  validation_status: 'not_applicable',
};

describe('StatementCard', () => {
  it('labels verified facts and interpretations distinctly (text + treatment, not colour alone)', () => {
    render(
      <>
        <StatementCard statement={fact} evidence={evidence} onOpenEvidence={() => undefined} />
        <StatementCard statement={inference} evidence={evidence} onOpenEvidence={() => undefined} />
      </>,
    );
    const factCard = screen.getByRole('article', { name: /Verified fact: Enrollment changed/ });
    const infCard = screen.getByRole('article', { name: /AI interpretation: A larger enrollment/ });
    expect(within(factCard).getByText('Verified fact')).toBeInTheDocument();
    expect(within(infCard).getByText('AI interpretation')).toBeInTheDocument();
    expect(within(infCard).queryByText('Verified fact')).not.toBeInTheDocument();
    expect(factCard).toHaveClass('stmt-fact');
    expect(infCard).toHaveClass('stmt-inference');
    expect(factCard.className).not.toEqual(infCard.className);
    expect(within(factCard).getByText('Evidence check: supported')).toBeInTheDocument();
    // interpretations cite evidence as a basis, never as verification
    expect(within(infCard).getByText('Based on:')).toBeInTheDocument();
    expect(within(factCard).getByText('Evidence:')).toBeInTheDocument();
  });

  it('renders unknowns and recommended investigations with their own labels', () => {
    render(
      <>
        <StatementCard statement={{ ...fact, statement_type: 'UNKNOWN', statement: 'Rationale not established.', evidence_ids: [], confidence: 'Not applicable' }} />
        <StatementCard statement={{ ...fact, statement_type: 'RECOMMENDED_INVESTIGATION', statement: 'Review registry history.', evidence_ids: [], confidence: 'Not applicable' }} />
      </>,
    );
    expect(screen.getByText('Unknown')).toBeInTheDocument();
    expect(screen.getByText('Recommended investigation')).toBeInTheDocument();
  });

  it('flags a fact without evidence', () => {
    render(<StatementCard statement={{ ...fact, evidence_ids: [] }} />);
    expect(screen.getByText('No evidence cited')).toBeInTheDocument();
  });

  it('opens evidence from the chip', async () => {
    const onOpen = vi.fn();
    render(<StatementCard statement={fact} evidence={evidence} onOpenEvidence={onOpen} />);
    await userEvent.click(screen.getByRole('button', { name: /Open evidence S1/ }));
    expect(onOpen).toHaveBeenCalledWith(evidence.S1);
  });
});
