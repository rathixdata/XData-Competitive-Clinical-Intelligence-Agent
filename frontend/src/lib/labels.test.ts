import { describe, expect, it } from 'vitest';
import { closeness, eventTypeLabel, humanizeEnum, predicateLabel, sourceLabel, statusLabel } from './labels';

describe('plain-language labels', () => {
  it('maps known machine identifiers', () => {
    expect(sourceLabel('ctgov')).toBe('ClinicalTrials.gov');
    expect(sourceLabel('openfda_drugsfda')).toBe('FDA approvals (Drugs@FDA)');
    expect(eventTypeLabel('ENDPOINT_CHANGED')).toBe('Primary endpoint changed');
    expect(predicateLabel('evaluated_in')).toBe('is being tested in');
    expect(statusLabel('never_run')).toBe('Not yet checked');
    expect(closeness(1)).toBe('100%');
  });

  it('falls back to a humanised form for unknown values', () => {
    expect(eventTypeLabel('SOMETHING_NEW')).toBe('Something new');
    expect(sourceLabel('brand_new_feed')).toBe('Brand new feed');
    expect(predicateLabel('works_with')).toBe('works with');
    expect(humanizeEnum(null)).toBe('-');
  });
});
