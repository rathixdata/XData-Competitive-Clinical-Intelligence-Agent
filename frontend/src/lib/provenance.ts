import type { Provenance } from '../api/types';
import { fmtDateTime } from './format';

export function provenanceText(p: Provenance | null): string {
  if (!p) return 'No provenance recorded';
  const parts = [`Source: ${p.source}`];
  if (p.snapshot_version !== undefined) parts.push(`snapshot v${p.snapshot_version}`);
  if (p.profile_version !== undefined) parts.push(`profile v${p.profile_version}`);
  if (p.retrieved_at) parts.push(`retrieved ${fmtDateTime(p.retrieved_at)}`);
  else if (p.updated_at) parts.push(`updated ${fmtDateTime(p.updated_at)}`);
  return parts.join(', ');
}
