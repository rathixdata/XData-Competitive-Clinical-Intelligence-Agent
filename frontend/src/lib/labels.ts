/**
 * Plain-language labels for every machine identifier the backend sends (enums, source keys,
 * relationship names, statuses). Business users never see raw codes: always render through
 * these helpers. Unknown values fall back to a humanised form (underscores -> spaces, sentence case).
 */

/** "NEW_PUBLICATION" -> "New publication"; "competes_with" -> "Competes with". */
export function humanizeEnum(v: string | null | undefined): string {
  if (!v) return '-';
  const s = v.replace(/[_-]+/g, ' ').trim().toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function lookup(map: Record<string, string>, v: string | null | undefined): string {
  if (!v) return '-';
  return map[v] ?? map[v.toLowerCase()] ?? humanizeEnum(v);
}

// ------------------------------------------------------------------ data sources
export const SOURCE_LABELS: Record<string, string> = {
  ctgov: 'ClinicalTrials.gov',
  clinicaltrials: 'ClinicalTrials.gov',
  pubmed: 'PubMed',
  openfda_label: 'FDA drug label',
  openfda_drugsfda: 'FDA approvals (Drugs@FDA)',
  sec_edgar: 'SEC filings',
  corporate_feed: 'Company press releases',
  conference_feed: 'Conference abstracts',
  internal: 'Your team',
  profile: 'Curated drug profile',
  analyst: 'Analyst',
};

export const SOURCE_DESCRIPTIONS: Record<string, string> = {
  ctgov: 'US registry of clinical trials: design, status, enrollment, endpoints and dates.',
  pubmed: 'Biomedical literature: new journal articles and abstracts.',
  openfda_label: 'Official FDA prescribing information (package inserts) and label updates.',
  openfda_drugsfda: 'FDA approval records, including supplemental approvals.',
  sec_edgar: 'Company filings with the US Securities and Exchange Commission (10-K, 8-K...).',
  corporate_feed: 'News and press releases from company investor-relations pages.',
  conference_feed: 'Abstracts presented at medical conferences.',
};

export function sourceLabel(v: string | null | undefined): string {
  return lookup(SOURCE_LABELS, v);
}

// ------------------------------------------------------------------ kinds of change
export const EVENT_TYPE_LABELS: Record<string, string> = {
  TRIAL_REGISTERED: 'New trial registered',
  TRIAL_STARTED: 'Trial started',
  STATUS_CHANGED: 'Trial status changed',
  PHASE_CHANGED: 'Trial phase changed',
  ENROLLMENT_CHANGED: 'Enrollment target changed',
  ENDPOINT_CHANGED: 'Primary endpoint changed',
  DATE_CHANGED: 'Timeline changed',
  ARM_CHANGED: 'Treatment arms changed',
  INTERVENTION_CHANGED: 'Treatment changed',
  ELIGIBILITY_CHANGED: 'Patient eligibility changed',
  SPONSOR_CHANGED: 'Sponsor changed',
  LOCATION_CHANGED: 'Trial sites changed',
  CONDITION_CHANGED: 'Disease studied changed',
  TITLE_CHANGED: 'Trial title changed',
  NEW_PUBLICATION: 'New publication',
  APPROVAL: 'FDA approval',
  SUPPLEMENTAL_APPROVAL: 'FDA supplemental approval',
  LABEL_CHANGED: 'FDA label updated',
  CORPORATE_EVENT: 'Company announcement',
  CONFERENCE_ABSTRACT: 'Conference abstract',
  // secondary tags
  TRIAL_HALTED: 'Trial halted',
  DELAY: 'Delay',
  ACCELERATION: 'Brought forward',
  ENDPOINT_REPLACED: 'Endpoint replaced',
  ENDPOINT_ADDED: 'Endpoint added',
  ENDPOINT_REMOVED: 'Endpoint removed',
  ENROLLMENT_INCREASE: 'Enrollment increased',
  ENROLLMENT_DECREASE: 'Enrollment decreased',
  PRIMARY_COMPLETION_DATE: 'Primary completion date',
  STUDY_COMPLETION_DATE: 'Study completion date',
  START_DATE: 'Start date',
  SITE_UPDATE: 'Site list updated',
  INDICATION_UPDATE: 'Approved use updated',
  SECTION_INDICATIONS_AND_USAGE: 'Label section: indications and usage',
  SECTION_BOXED_WARNING: 'Label section: boxed warning',
  SECTION_WARNINGS_AND_CAUTIONS: 'Label section: warnings',
  SECTION_DOSAGE_AND_ADMINISTRATION: 'Label section: dosing',
  SECTION_ADVERSE_REACTIONS: 'Label section: side effects',
  CLINICAL_TRIAL: 'Clinical trial results',
  REVIEW: 'Review article',
  META_ANALYSIS: 'Meta-analysis',
  CASE_REPORT: 'Case report',
};

export function eventTypeLabel(v: string | null | undefined): string {
  return lookup(EVENT_TYPE_LABELS, v);
}

/** Field-level change kinds in the "What changed" table (added / removed / modified...). */
export const CHANGE_KIND_LABELS: Record<string, string> = {
  added: 'Added',
  removed: 'Removed',
  modified: 'Changed',
  changed: 'Changed',
  replaced: 'Replaced',
  increased: 'Increased',
  decreased: 'Decreased',
};
export function changeKindLabel(v: string | null | undefined): string {
  if (v && EVENT_TYPE_LABELS[v]) return EVENT_TYPE_LABELS[v];
  return lookup(CHANGE_KIND_LABELS, v);
}

// ------------------------------------------------------------------ knowledge-graph relationships
export const PREDICATE_LABELS: Record<string, string> = {
  develops: 'develops',
  targets: 'targets',
  has_mechanism: 'works by',
  has_modality: 'is a',
  evaluated_in: 'is being tested in',
  studies: 'studies',
  uses_endpoint: 'measures',
  enrolls_biomarker: 'enrolls patients with',
  competes_with: 'competes with',
  authored: 'wrote',
  mentions: 'mentions',
  received_regulatory_event: 'had regulatory event',
  sponsors: 'sponsors',
  disclosed: 'announced',
  indicated_for: 'is approved/used for',
};

export function predicateLabel(v: string | null | undefined): string {
  if (!v) return '-';
  return PREDICATE_LABELS[v] ?? v.replace(/_/g, ' ');
}

// ------------------------------------------------------------------ statuses
export const STATUS_LABELS: Record<string, string> = {
  // intelligence events
  published: 'New',
  acknowledged: 'Reviewed',
  escalated: 'Escalated',
  blocked: 'Held back',
  archived: 'Archived',
  // briefs
  draft: 'Draft',
  in_review: 'In review',
  approved: 'Approved',
  distributed: 'Sent',
  // connectors / runs
  healthy: 'Up to date',
  stale: 'Out of date',
  failing: 'Failing',
  failed: 'Failed',
  never_run: 'Not yet checked',
  disabled: 'Turned off',
  running: 'Updating now',
  succeeded: 'Succeeded',
  partial: 'Partly succeeded',
  // deliveries
  pending: 'Waiting to send',
  sent: 'Sent',
  dead: 'Gave up after retries',
  read: 'Read',
  // generic
  active: 'Active',
  inactive: 'Inactive',
  pending_review: 'Waiting for review',
  rejected: 'Rejected',
  auto_linked: 'Matched automatically',
};

export const STATUS_DESCRIPTIONS: Record<string, string> = {
  published: 'Newly detected and visible in the change feed; nobody has marked it as reviewed yet.',
  acknowledged: 'An analyst has looked at this and marked it as reviewed.',
  escalated: 'Flagged to a lead or stakeholders for attention.',
  blocked: 'Held back from the feed because the AI summary failed evidence checks.',
  archived: 'Stored for completeness; no action needed.',
  draft: 'Being prepared; not yet reviewed.',
  in_review: 'Edited or submitted and waiting for approval.',
  approved: 'Approved and locked; ready to send.',
  distributed: 'Sent to recipients.',
  healthy: 'This source was checked recently, within its target schedule.',
  stale: 'This source has not been checked recently enough; recent changes may be missing.',
  failing: 'Recent attempts to check this source failed.',
  never_run: 'This source has never been checked yet.',
  disabled: 'This source is switched off.',
};

export function statusLabel(v: string | null | undefined): string {
  return lookup(STATUS_LABELS, v);
}

/** Connector state phrased for the "data may be missing" banner. */
export function sourceStateLabel(v: string | null | undefined): string {
  if (v === 'never_run') return 'not yet checked';
  if (v === 'stale') return 'out of date';
  if (v === 'failing' || v === 'failed') return 'update failing';
  if (v === 'disabled') return 'turned off';
  return statusLabel(v).toLowerCase();
}

// ------------------------------------------------------------------ AI review status
export const REVIEW_LABELS: Record<string, { label: string; description: string }> = {
  Machine: { label: 'AI-written · not reviewed', description: 'AI-written, not yet checked by an analyst.' },
  'Analyst-reviewed': { label: 'Analyst-reviewed', description: 'A human analyst has checked this AI output.' },
  Approved: { label: 'Approved by analyst', description: 'A human analyst checked and approved this output.' },
};

// ------------------------------------------------------------------ score dimensions
export const DIMENSION_LABELS: Record<string, { name: string; description: string }> = {
  R: { name: 'Relevance to your portfolio', description: 'Is this about something in your landscape, and does it touch one of your drugs?' },
  C: { name: 'Size of the change', description: 'How big and meaningful the change itself is (for example a replaced primary endpoint).' },
  P: { name: 'How close to your drug', description: 'How similar the competitor is to your drug (same target, disease, patients, line of therapy...).' },
  T: { name: 'Timing', description: 'How soon a related milestone (readout, approval) is expected.' },
  N: { name: 'Novelty', description: 'Whether this is new information or a repeat of something already seen.' },
};

export function dimensionName(code: string): string {
  return DIMENSION_LABELS[code]?.name ?? humanizeEnum(code);
}

/** Proximity 0..1 -> "100%". */
export function closeness(p: number | null | undefined): string {
  if (p === null || p === undefined || Number.isNaN(p)) return '-';
  return `${Math.round(p * 100)}%`;
}

export const CLOSENESS_HELP =
  'How similar the competitor is to your drug: 100% means the same target, disease, patient group and line of therapy; lower means fewer things in common.';

// ------------------------------------------------------------------ entities, roles, misc
export const ENTITY_TYPE_LABELS: Record<string, string> = {
  company: 'Company',
  asset: 'Drug',
  trial: 'Trial',
  target: 'Biological target',
  mechanism: 'Mechanism of action',
  indication: 'Disease',
  biomarker: 'Biomarker',
  endpoint: 'Endpoint',
  modality: 'Drug type',
  line_of_therapy: 'Line of therapy',
  conference: 'Conference',
  kol: 'Key opinion leader',
  publication: 'Publication',
  regulatory_event: 'Regulatory event',
  disclosure: 'Company disclosure',
  catalyst: 'Milestone',
  event: 'Detected change',
  profile: 'Profile update',
};
export function entityTypeLabel(v: string | null | undefined): string {
  return lookup(ENTITY_TYPE_LABELS, v);
}

export const ROLE_LABELS: Record<string, string> = {
  customer: 'Your drug',
  competitor: 'Competitor',
  monitored: 'Monitored',
};
export function roleLabel(v: string | null | undefined): string {
  return lookup(ROLE_LABELS, v);
}

export const MATCH_METHOD_LABELS: Record<string, string> = {
  exact_alias: 'Exact name match',
  normalized_alias: 'Name match (ignoring spelling/format)',
  ambiguous_alias: 'Name matches more than one thing',
  fuzzy: 'Similar spelling',
  fuzzy_alias: 'Similar spelling',
  embedding: 'Similar meaning (AI)',
  identifier: 'Matched by ID',
  manual: 'Matched by an analyst',
};
export function matchMethodLabel(v: string | null | undefined): string {
  return lookup(MATCH_METHOD_LABELS, v);
}

export const ALIAS_TYPE_LABELS: Record<string, string> = {
  synonym: 'Synonym',
  dev_code: 'Development code (e.g. CA-201)',
  generic: 'Generic name',
  brand: 'Brand name',
  legacy: 'Former name',
  abbreviation: 'Abbreviation',
  spelling: 'Alternative spelling',
};

export const CHANNEL_LABELS: Record<string, string> = {
  web: 'In-app inbox',
  email: 'Email',
  slack: 'Slack',
  teams: 'Microsoft Teams',
  webhook: 'Webhook (for IT integrations)',
};
export function channelLabel(v: string | null | undefined): string {
  return lookup(CHANNEL_LABELS, v);
}

export const CADENCE_LABELS: Record<string, string> = {
  immediate: 'Immediately',
  daily: 'Daily digest',
  weekly: 'Weekly digest',
};

export const NOTIFICATION_KIND_LABELS: Record<string, string> = {
  alert: 'Alert',
  digest: 'Digest',
  escalation: 'Escalation',
  test: 'Test message',
  report: 'Brief',
  brief: 'Brief',
};
export function notificationKindLabel(v: string | null | undefined): string {
  return lookup(NOTIFICATION_KIND_LABELS, v);
}

export const VISIBILITY_LABELS: Record<string, string> = {
  private: 'Only me',
  team: 'My team',
  tenant: 'Everyone in my organisation',
};
export function visibilityLabel(v: string | null | undefined): string {
  return lookup(VISIBILITY_LABELS, v);
}

export const CONFIDENCE_DESCRIPTIONS: Record<string, string> = {
  Verified: 'Directly supported by the cited source record.',
  High: 'Strong supporting evidence.',
  Medium: 'Some supporting evidence; treat as likely, not certain.',
  Low: 'Weak evidence; treat as a hypothesis.',
};
