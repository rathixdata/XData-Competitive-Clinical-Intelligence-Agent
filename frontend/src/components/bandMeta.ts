import type { Band } from '../api/types';

export const BAND_CLASS: Record<Band, string> = {
  Archive: 'band-archive',
  Feed: 'band-feed',
  'Analyst Review': 'band-analyst-review',
  'High Priority': 'band-high-priority',
  'Executive Alert': 'band-executive-alert',
};

/** One-line tooltip per priority band. */
export const BAND_DESCRIPTION: Record<Band, string> = {
  Archive: 'Archive: low importance; stored for completeness only',
  Feed: 'Feed: worth knowing; appears in the change feed',
  'Analyst Review': 'Analyst review: an analyst should check whether it matters',
  'High Priority': 'High priority: likely to matter to your drug; review soon',
  'Executive Alert': 'Executive alert: highest importance; leadership should hear about it',
};

/** Plain-language legend: what each band means and what to do. Thresholds are the defaults; landscapes may override. */
export const BAND_INFO: { band: Band; min: number; meaning: string; action: string }[] = [
  { band: 'Executive Alert', min: 85, meaning: 'Major change that directly affects one of your drugs.', action: 'Read today and brief leadership.' },
  { band: 'High Priority', min: 70, meaning: 'Likely to matter to your drug strategy.', action: 'Review this week; consider escalating.' },
  { band: 'Analyst Review', min: 50, meaning: 'Might matter; needs an expert eye.', action: 'An analyst should check and decide.' },
  { band: 'Feed', min: 30, meaning: 'Worth knowing, low direct impact.', action: 'Skim when convenient.' },
  { band: 'Archive', min: 0, meaning: 'Minor or unrelated change.', action: 'No action; kept for the record.' },
];

export function bandClass(band: string | null | undefined): string {
  return (band && BAND_CLASS[band as Band]) || 'band-archive';
}
