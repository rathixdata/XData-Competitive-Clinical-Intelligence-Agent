import type { Statement } from '../api/types';

/** Client-side mirror of PUT /events/{id}/narrative rules (server re-validates). */
export function validateDraft(statements: Statement[], reason: string, evidenceIds: string[]): string[] {
  const errs: string[] = [];
  if (reason.trim().length < 3) errs.push('A reason for the edit is required (at least 3 characters).');
  if (statements.length === 0) errs.push('At least one statement is required.');
  statements.forEach((s, i) => {
    if (s.statement.trim().length < 3) errs.push(`Statement ${i + 1}: text is too short.`);
    if (s.statement_type === 'FACT') {
      if (s.evidence_ids.length === 0) errs.push(`Statement ${i + 1}: a Verified fact must cite at least one retained evidence item.`);
      const unknown = s.evidence_ids.filter((e) => !evidenceIds.includes(e));
      if (unknown.length) errs.push(`Statement ${i + 1}: unknown evidence ${unknown.join(', ')} (edits cannot introduce new evidence).`);
    }
  });
  return errs;
}
