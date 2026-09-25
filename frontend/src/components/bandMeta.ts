import type { Band } from '../api/types';

export const BAND_CLASS: Record<Band, string> = {
  Archive: 'band-archive',
  Feed: 'band-feed',
  'Analyst Review': 'band-analyst-review',
  'High Priority': 'band-high-priority',
  'Executive Alert': 'band-executive-alert',
};

export const BAND_DESCRIPTION: Record<Band, string> = {
  Archive: 'Stored for completeness; below feed threshold',
  Feed: 'Visible in the intelligence feed',
  'Analyst Review': 'Needs analyst review',
  'High Priority': 'High-priority development',
  'Executive Alert': 'Executive alert: highest materiality',
};

export function bandClass(band: string | null | undefined): string {
  return (band && BAND_CLASS[band as Band]) || 'band-archive';
}
