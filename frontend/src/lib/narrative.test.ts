import { describe, expect, it } from 'vitest';
import { validateDraft } from './narrative';

describe('validateDraft (narrative editor)', () => {
  const base = { section: 'what_changed', confidence: 'Verified', statement: 'Enrollment changed from 320 to 480.' };
  it('requires a reason and evidence for facts', () => {
    const errs = validateDraft([{ ...base, statement_type: 'FACT', evidence_ids: [] }], '', ['S1']);
    expect(errs.some((e) => e.includes('reason'))).toBe(true);
    expect(errs.some((e) => e.includes('must cite'))).toBe(true);
  });
  it('rejects evidence ids that were not retained', () => {
    const errs = validateDraft([{ ...base, statement_type: 'FACT', evidence_ids: ['S9'] }], 'fix typo', ['S1']);
    expect(errs).toEqual(['Statement 1: unknown evidence S9 (edits cannot introduce new evidence).']);
  });
  it('accepts interpretations without evidence', () => {
    expect(validateDraft([{ ...base, statement_type: 'INFERENCE', confidence: 'Medium', evidence_ids: [] }], 'clarify', ['S1'])).toEqual([]);
  });
});
