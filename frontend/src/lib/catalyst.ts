import type { Catalyst } from '../api/types';
import { fmtDate } from './format';

type Dated = Pick<Catalyst, 'expected_date' | 'window_start' | 'window_end'>;

export function catalystDate(c: Dated): string {
  if (c.expected_date) return fmtDate(c.expected_date);
  if (c.window_start) return `${fmtDate(c.window_start)} - ${fmtDate(c.window_end)}`;
  return 'Date unknown';
}

/** Previous date/window of a changed catalyst (last `history` entry). */
export function previousDate(prev: Record<string, unknown> | null | undefined): string | null {
  if (!prev) return null;
  const p = prev as { expected_date?: string | null; window_start?: string | null; window_end?: string | null };
  if (!p.expected_date && !p.window_start) return null;
  return catalystDate({ expected_date: p.expected_date ?? null, window_start: p.window_start ?? null, window_end: p.window_end ?? null });
}

/** Date used to place a catalyst on the calendar (expected date, else window start). */
export function anchorDate(c: Dated): string | null {
  return c.expected_date ?? c.window_start ?? null;
}
