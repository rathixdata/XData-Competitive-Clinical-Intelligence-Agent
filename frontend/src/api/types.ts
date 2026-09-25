/**
 * Hand-written types mirroring the backend (/api/v1) response shapes.
 * Source of truth: backend/app/api/v1/*.py and docs/openapi.json. Fields the UI does not
 * use are typed loosely (`unknown` / index signatures) so backend additions never break the build.
 */

export type UUID = string;
export type ISODate = string;

export interface Paged<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown };
}

// ------------------------------------------------------------------ auth
export interface TokenOut {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface User {
  id: UUID;
  email: string;
  display_name: string | null;
  roles: string[];
  team: string | null;
  is_active: boolean;
  last_login_at: ISODate | null;
  created_at?: ISODate;
  tenant_id?: UUID;
}

export interface Me {
  user: User;
  tenant: { id: UUID; name: string; slug: string; deployment_mode: string } | null;
  roles: string[];
  permissions: string[];
  auth_method: string;
  available_roles: string[];
}

// ------------------------------------------------------------------ taxonomy
export const BANDS = ['Archive', 'Feed', 'Analyst Review', 'High Priority', 'Executive Alert'] as const;
export type Band = (typeof BANDS)[number];

export const STATEMENT_TYPES = ['FACT', 'INFERENCE', 'UNKNOWN', 'RECOMMENDED_INVESTIGATION'] as const;
export type StatementType = (typeof STATEMENT_TYPES)[number];

export const CONFIDENCES = ['Verified', 'High', 'Medium', 'Low', 'Not applicable'] as const;
export type Confidence = (typeof CONFIDENCES)[number];

export const FEEDBACK_LABELS = [
  'USEFUL',
  'NOT_USEFUL',
  'MATERIAL',
  'NOT_MATERIAL',
  'WRONG_MAPPING',
  'INCORRECT_INTERPRETATION',
  'ALREADY_KNOWN',
  'ESCALATE',
] as const;
export type FeedbackLabel = (typeof FEEDBACK_LABELS)[number];

export const EVENT_STATUSES = ['published', 'acknowledged', 'escalated', 'blocked', 'archived', 'pending'] as const;

// ------------------------------------------------------------------ graph / impact
export interface PathHop {
  from: UUID;
  to: UUID;
  from_label?: string;
  to_label?: string;
  predicate: string;
  method?: string;
  confidence?: number;
  edge_id?: UUID;
}

export interface ProximityDimension {
  known: boolean;
  score: number;
  shared: string[];
  weight: number;
}

export interface ImpactMapping {
  asset_id: UUID;
  asset_name: string;
  via_asset_id?: UUID | null;
  proximity: number;
  rationale: string;
  path: PathHop[];
  detail?: {
    rule?: string;
    basis?: string;
    score?: number;
    coverage?: number;
    rationale?: string;
    dimensions?: Record<string, ProximityDimension>;
  };
}

// ------------------------------------------------------------------ events
export interface IntelEvent {
  id: UUID;
  landscape_id: UUID | null;
  object_type: string;
  object_id: UUID;
  source: string;
  primary_type: string;
  secondary_tags: string[];
  title: string;
  change_ids: UUID[];
  related_entity_ids: UUID[];
  facet_terms: string[];
  company_id: UUID | null;
  asset_id: UUID | null;
  impacted_asset_ids: UUID[];
  impacted_assets: ImpactMapping[] | null;
  materiality_score: number;
  band: Band;
  status: string;
  review_status: string;
  version: number;
  update_summary: string[];
  current_narrative_id: UUID | null;
  publication_blocked_reason: string | null;
  occurred_at: ISODate | null;
  source_fetched_at: ISODate | null;
  detected_at: ISODate;
  scored_at?: ISODate | null;
  published_at: ISODate | null;
  acknowledged_by: string | null;
  model_confidence?: string | null;
  personal_boost?: number;
  score_components?: ScoreExplanation;
}

export interface ScoreDimension {
  score: number;
  weight: number;
  rule_hits: string[];
  contribution: number;
}

export interface ScoreExplanation {
  formula?: string;
  version?: string;
  dimensions: Record<string, ScoreDimension>;
  proximity_rule?: string;
  band_thresholds?: Record<string, number>;
  model_confidence?: string;
  mapping_confidence?: number;
}

export interface SourceRights {
  license?: string;
  terms_url?: string;
  attribution?: string;
  redistribution?: string;
  [k: string]: unknown;
}

export interface SnapshotRef {
  id: UUID;
  version: number;
  retrieved_at: ISODate;
}

export interface SourceDocumentRef {
  id: UUID;
  source: string;
  uri: string | null;
  title?: string | null;
  retrieved_at: ISODate;
  checksum?: string;
  rights?: SourceRights | null;
  connector_version?: string;
}

export interface ChangeRecord {
  id: UUID;
  field: string;
  change_type: string;
  secondary_tags: string[];
  old_value: unknown;
  new_value: unknown;
  magnitude?: Record<string, unknown> | null;
  suppressed?: boolean;
  detected_at?: ISODate;
  source?: string;
  from_snapshot: SnapshotRef | null;
  to_snapshot: SnapshotRef | null;
  source_document: SourceDocumentRef | null;
}

export interface EvidenceLink {
  evidence_id: string;
  kind: string; // structured_field | passage | change_event | ...
  source?: string;
  source_type?: string;
  source_document_id?: UUID | null;
  snapshot_id?: UUID | null;
  chunk_id?: UUID | null;
  change_id?: UUID | null;
  object_type?: string | null;
  object_id?: UUID | null;
  uri?: string | null;
  title?: string | null;
  section?: string | null;
  field_path?: string | null;
  span?: [number, number] | null;
  retrieved_at?: ISODate | null;
  published_at?: ISODate | null;
  score?: number;
  is_current?: boolean;
  rights?: SourceRights | null;
  excerpt?: string | null;
  content_hash?: string;
}

export interface Statement {
  section: string;
  statement: string;
  statement_type: StatementType;
  confidence: Confidence | string;
  evidence_ids: string[];
  affected_entity_ids?: string[];
  validation_status?: string;
  validation_detail?: Record<string, unknown> | null;
  original_statement_type?: string | null;
}

export interface Claim extends Statement {
  id: UUID;
  artifact_id: UUID;
  ordinal: number;
  evidence_links: EvidenceLink[];
  review_status: string;
}

export interface ValidationSummary {
  counts: Record<string, number>;
  withheld: Statement[];
  publishable: boolean;
  blocked_reasons: string[];
  validator_version?: string;
  fallback_used?: boolean;
  judge_generation_id?: UUID | null;
}

export interface NarrativeContent {
  headline?: string;
  sections?: Record<string, Statement[]>;
  evidence?: Record<string, EvidenceLink>;
  mappings?: ImpactMapping[];
  fallback_of?: string | null;
  [k: string]: unknown;
}

export interface Artifact {
  id: UUID;
  kind: string;
  intel_event_id?: UUID | null;
  content: NarrativeContent;
  validation: ValidationSummary | null;
  publishable: boolean;
  review_status: string;
  is_human_edited: boolean;
  parent_id: UUID | null;
  edited_by: string | null;
  edit_reason: string | null;
  model_workflow_version: string;
  created_at: ISODate;
  claims: Claim[];
}

export interface NarrativeHistoryItem {
  id: UUID;
  created_at: ISODate;
  is_human_edited: boolean;
  edited_by: string | null;
  review_status: string;
  publishable: boolean;
  parent_id: UUID | null;
  model_workflow_version: string;
  fallback_used: boolean;
}

export interface FeedbackRecord {
  id: UUID;
  label: FeedbackLabel;
  reason: string | null;
  comment: string | null;
  created_at: ISODate;
  intel_event_id: UUID;
}

export interface EventDetail {
  event: IntelEvent;
  changes: ChangeRecord[];
  score_explanation: ScoreExplanation | null;
  impacts: ImpactMapping[] | null;
  narrative: Artifact | null;
  narrative_history: NarrativeHistoryItem[];
  feedback: { counts: Partial<Record<FeedbackLabel, number>>; mine: FeedbackRecord[] };
  explanation?: EventExplanation;
}

export type Facets = Record<string, { value: string; count: number }[]>;

export interface EventFilters {
  landscape_id?: string;
  from?: string;
  to?: string;
  min_score?: string;
  band?: string[];
  event_type?: string[];
  source?: string[];
  status?: string[];
  company_id?: string;
  asset_id?: string;
  impacted_asset_id?: string;
  mechanism?: string;
  indication?: string;
  q?: string;
  sort?: string;
  personalize?: string;
  offset?: string;
}

export interface EvidenceContext {
  chunk: {
    id: UUID;
    text: string;
    section: string | null;
    title: string | null;
    uri: string | null;
    retrieved_at: ISODate | null;
    published_at: ISODate | null;
    source: string;
    meta?: { rights?: SourceRights };
  };
  context: { chunk_id: UUID; index: number; section: string | null; text: string; is_target: boolean }[];
  document: {
    id: UUID;
    source: string;
    uri: string | null;
    title?: string | null;
    retrieved_at: ISODate;
    checksum?: string;
    rights?: SourceRights | null;
    connector_version?: string;
    source_last_updated?: string | null;
  };
}

// ------------------------------------------------------------------ portfolio
export interface Catalyst {
  id: UUID;
  event_type: string;
  title: string;
  asset_id: UUID | null;
  trial_id: UUID | null;
  company_id: UUID | null;
  expected_date: string | null;
  window_start: string | null;
  window_end: string | null;
  date_basis: 'SOURCED' | 'INFERRED';
  date_precision: string | null;
  confidence: string | null;
  source_document_id: UUID | null;
  evidence: Record<string, unknown> | null;
  history: Record<string, unknown>[];
  status: string;
  asset_name?: string | null;
  nct_id?: string | null;
  changed?: boolean;
  previous?: Record<string, unknown> | null;
}

export interface CatalystResponse {
  from: string;
  to: string;
  items: Catalyst[];
  legend: Record<string, string>;
}

export interface HealthSummary {
  connectors: number;
  healthy: number;
  stale_or_failing: { key: string; display_name: string; state: string; hours_since_success: number | null }[];
  banner: string | null;
}

export interface AssetCard {
  asset_id: UUID;
  name: string;
  stage: string | null;
  profile: Record<string, unknown> | null;
  landscape_id: UUID;
  open_high_priority: number;
  events_30d: number;
}

export interface Dashboard {
  landscapes: { id: UUID; name: string }[];
  assets: AssetCard[];
  material_developments: Pick<
    IntelEvent,
    'id' | 'title' | 'materiality_score' | 'band' | 'primary_type' | 'detected_at' | 'status' | 'review_status' | 'impacted_assets'
  >[];
  upcoming_catalysts: Catalyst[];
  health: HealthSummary;
  watchlists: { id: UUID; name: string; visibility: string }[];
  band_counts_30d: Partial<Record<Band, number>>;
}

export interface Provenance {
  source: string;
  field?: string;
  snapshot_id?: UUID;
  snapshot_version?: number;
  source_document_id?: UUID;
  retrieved_at?: ISODate;
  updated_at?: ISODate;
  profile_version?: number;
  uri?: string;
}

export interface MatrixCell {
  value: unknown;
  provenance: Provenance | null;
}

export interface MatrixRow {
  asset_id: UUID;
  asset: string;
  role: string;
  is_internal: boolean;
  status: string;
  cells: Record<string, MatrixCell>;
  trials: string[];
  stale: boolean;
}

export interface Matrix {
  landscape_id: UUID;
  columns: string[];
  rows: MatrixRow[];
  note?: string;
}

export interface Comparison {
  columns: string[];
  rows: MatrixRow[];
  context_warnings: string[];
  generated_at: ISODate;
}

export interface KPIs {
  window_days: number;
  events: number;
  by_band: Record<string, number>;
  source_attribution_rate: number | null;
  high_priority_precision: number | null;
  useful_alert_rate: number | null;
  blocked_publications: number;
  median_fetch_to_publish_minutes: number | null;
  p95_fetch_to_publish_minutes: number | null;
  feedback_count: number;
  targets: Record<string, number>;
}

// ------------------------------------------------------------------ landscapes
export interface LandscapeConfig {
  band_thresholds?: Record<string, number>;
  materiality_weights?: Record<string, number>;
  indications?: string[];
  [k: string]: unknown;
}

export interface Landscape {
  id: UUID;
  name: string;
  description: string | null;
  disease: string | null;
  geographies: string[];
  status: string;
  config: LandscapeConfig;
  template_id: UUID | null;
  version: number;
  created_at: ISODate;
  updated_at: ISODate;
  member_counts?: Record<string, number>;
}

export interface LandscapeMember {
  id: UUID;
  landscape_id: UUID;
  entity_type: 'asset' | 'company' | 'trial';
  entity_id: UUID;
  role: 'customer' | 'competitor' | 'monitored';
  label: string | null;
  status: string | null;
}

export interface LandscapeDetail extends Landscape {
  members: LandscapeMember[];
}

export interface GraphNode {
  id: UUID;
  type: string;
  label: string;
  role: string | null;
}

export interface GraphEdge {
  id: UUID;
  source: UUID;
  target: UUID;
  predicate: string;
  confidence: number;
  method: string;
  status: string;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Template {
  id: UUID;
  name: string;
  therapeutic_area: string | null;
  description: string | null;
  config: LandscapeConfig;
}

export type Visibility = 'private' | 'team' | 'tenant';

export interface Watchlist {
  id: UUID;
  name: string;
  description: string | null;
  visibility: Visibility;
  landscape_id: UUID | null;
  alert_policy_id: UUID | null;
  owner_id?: UUID;
  item_count?: number;
  owned?: boolean;
  created_at?: ISODate;
}

export interface WatchlistItem {
  id: UUID;
  item_type: string;
  entity_id: UUID | null;
  value: string;
  added_by: string | null;
  created_at?: ISODate;
}

export interface WatchlistDetail extends Watchlist {
  items: WatchlistItem[];
}

export interface SavedView {
  id: UUID;
  name: string;
  view: 'feed' | 'calendar' | 'matrix' | 'compare';
  filters: Record<string, unknown>;
  visibility: Visibility;
  owned: boolean;
}

// ------------------------------------------------------------------ entities / assets
export interface EntitySearchHit {
  id: UUID;
  type: string;
  name: string;
  matched_alias?: string;
  score: number;
  status: string | null;
  private: boolean;
}

export interface EntityLink {
  id: UUID;
  mention: string;
  entity_type: string;
  context_type: string | null;
  context_id: UUID | null;
  context_label?: string | null;
  entity_id: UUID | null;
  confidence: number;
  method: string;
  status: string;
  candidates: { alias?: string; score?: number; entity_id?: UUID; name?: string }[];
  reviewed_by: string | null;
  review_reason: string | null;
  updated_at: ISODate;
}

export interface Asset {
  id: UUID;
  canonical_name: string;
  owner_company_id: UUID | null;
  is_internal: boolean;
  modality: string | null;
  stage: string | null;
  profile: Record<string, unknown>;
  profile_version: number;
  status: string;
}

export interface Trial {
  id: UUID;
  nct_id: string;
  title: string;
  status: string | null;
  phase: string | null;
  sponsor_name?: string | null;
  enrollment?: number | null;
  primary_completion_date?: string | null;
  primary_endpoints?: (string | null)[];
  [k: string]: unknown;
}

export interface AssetDetail {
  asset: Asset;
  company: { id: UUID; canonical_name: string } | null;
  trials: Trial[];
  publications: { id: UUID; title: string; pub_date: string | null; journal?: string | null; pmid?: string | null; [k: string]: unknown }[];
  regulatory_events: { id: UUID; event_type: string; product_name: string; event_date: string | null; [k: string]: unknown }[];
  catalysts: Catalyst[];
  timeline: { date: string | null; kind: 'event' | 'regulatory' | 'publication'; title: string; id: UUID; band?: Band }[];
}

export interface ProfileVersion {
  id: UUID;
  asset_id: UUID;
  version: number;
  profile: Record<string, unknown>;
  changed_by: string | null;
  reason: string | null;
  changed_at: ISODate;
}

export interface ProfileField {
  id: UUID;
  key: string;
  label: string;
  field_type: 'text' | 'number' | 'date' | 'enum' | 'list';
  required: boolean;
  options: string[];
  sort_order: number;
  description: string | null;
}

// ------------------------------------------------------------------ ask
export interface AskAnswer {
  session_id: UUID;
  turn_id: UUID;
  artifact_id: UUID;
  question: string;
  answer: string;
  statements: Statement[];
  evidence: Record<string, EvidenceLink>;
  sources: { source_type: string; uri: string }[];
  confidence: string;
  limitations: string[];
  comparison_warning: string;
  abstained: boolean;
  explanation?: AnswerExplanation;
  resolved_context?: {
    entity_ids?: UUID[];
    entity_labels?: Record<string, string>;
    since?: string | null;
    comparison?: boolean;
  };
  generated_at: ISODate;
  model_workflow_version: string;
  validation?: ValidationSummary;
}

export type AskStage = 'planned' | 'retrieved' | 'generated' | 'validated';

export interface AskProgress {
  stage: AskStage;
  [k: string]: unknown;
}

export interface AskSession {
  id: UUID;
  title?: string | null;
  created_at: ISODate;
  updated_at: ISODate;
  landscape_id?: UUID | null;
  [k: string]: unknown;
}

export interface AskSessionDetail extends AskSession {
  turns: {
    turn_id: UUID;
    question: string;
    created_at: ISODate;
    artifact_id: UUID | null;
    answer: Omit<AskAnswer, 'session_id' | 'turn_id' | 'artifact_id'> | null;
  }[];
}

// ------------------------------------------------------------------ reports
export type ReportStatus = 'draft' | 'in_review' | 'approved' | 'distributed';

export interface BriefDevelopment {
  event_id: UUID;
  headline: string;
  so_what: string;
}

export interface BriefEventDigest {
  event_id: UUID;
  title: string;
  type: string;
  score: number;
  band: Band;
  detected_at: string;
  affected_assets: string[];
  facts: { statement: string; evidence_ids: string[] }[];
  inferences: string[];
  unknowns: string[];
  review_status: string;
}

export interface BriefContent {
  title?: string;
  period?: { start: string; end: string };
  executive_summary?: string;
  source_event_ids?: UUID[];
  top_developments?: BriefDevelopment[];
  watch_items?: string[];
  sections?: {
    top?: BriefEventDigest[];
    catalysts?: {
      catalyst_id: UUID;
      title: string;
      expected_date: string | null;
      window: [string, string] | null;
      date_basis: 'SOURCED' | 'INFERRED';
      confidence: string | null;
      asset: string | null;
    }[];
    new_entrants?: { event_id: UUID; title: string }[];
    regulatory_scientific?: { event_id: UUID; title: string; type: string }[];
    low_materiality_summary?: { count: number; by_type: Record<string, number>; note: string };
    event_count?: number;
  };
  generated_at?: ISODate;
  model_workflow_version?: string;
  disclaimer?: string;
  edited_by?: string;
  edited_at?: ISODate;
}

export interface Report {
  id: UUID;
  landscape_id: UUID;
  kind: string;
  title: string;
  period_start: string;
  period_end: string;
  status: ReportStatus;
  artifact_id: UUID | null;
  edited_artifact_id: UUID | null;
  distribution_list: string[];
  created_by: string | null;
  approved_by: string | null;
  approved_at: ISODate | null;
  distributed_at: ISODate | null;
  created_at: ISODate;
  updated_at?: ISODate;
}

export interface ReportDetail extends Report {
  content: BriefContent;
  original_content?: BriefContent | null;
}

// ------------------------------------------------------------------ alerts
export type Channel = 'web' | 'email' | 'slack' | 'teams' | 'webhook';
export const CHANNELS: Channel[] = ['web', 'email', 'slack', 'teams', 'webhook'];

export interface AlertPolicy {
  id: UUID;
  name: string;
  landscape_id: UUID | null;
  cadence: 'immediate' | 'daily' | 'weekly';
  min_score: number;
  event_types: string[];
  entity_ids: UUID[];
  watchlist_id: UUID | null;
  channels: Channel[];
  destinations: { email: string[]; slack_webhook: string | null; teams_webhook: string | null; webhook_url: string | null };
  active: boolean;
  created_at?: ISODate;
}

export interface AlertPolicyInput {
  name: string;
  landscape_id?: UUID | null;
  cadence: 'immediate' | 'daily' | 'weekly';
  min_score: number;
  event_types: string[];
  entity_ids: UUID[];
  watchlist_id?: UUID | null;
  channels: Channel[];
  destinations: { email: string[]; slack_webhook?: string | null; teams_webhook?: string | null; webhook_url?: string | null };
  active: boolean;
}

export interface AlertPreview {
  window_days: number;
  matching_events: number;
  events_per_week: number;
  estimated_deliveries_per_week: number;
  by_band: Record<string, number>;
  by_event_type: Record<string, number>;
  sample_event_ids: UUID[];
}

export interface Notification {
  id: UUID;
  dedupe_key: string;
  policy_id: UUID | null;
  user_id: UUID | null;
  intel_event_ids: UUID[];
  kind: string;
  channel: string;
  status: string;
  attempts: number;
  last_error: string | null;
  payload: { title?: string; event_id?: string; note?: string | null; verified_change?: string[]; [k: string]: unknown };
  created_at: ISODate;
  sent_at: ISODate | null;
}

// ------------------------------------------------------------------ admin
export interface ConnectorHealth {
  key: string;
  display_name: string;
  enabled: boolean;
  adapter_version: string;
  schedule_cron: string;
  rate_limit_per_sec: number;
  freshness_slo_hours: number;
  last_success_at: ISODate | null;
  next_run_at: ISODate | null;
  hours_since_success: number | null;
  state: string;
  stale: boolean;
  failures_last_7d: number;
  last_run: {
    id: UUID;
    status: string;
    started_at: ISODate;
    finished_at: ISODate | null;
    records_fetched: number;
    records_new: number;
    records_changed: number;
    changes_emitted: number;
    errors: number;
    message: string | null;
  } | null;
}

export interface ConnectorRun {
  id: UUID;
  connector_key: string;
  trigger: string;
  status: string;
  started_at: ISODate;
  finished_at: ISODate | null;
  records_fetched: number;
  records_new: number;
  records_changed: number;
  records_unchanged?: number;
  changes_emitted: number;
  errors: number;
  message: string | null;
  requested_by: string | null;
}

export interface ProximityRule {
  id: UUID;
  name: string;
  landscape_id: UUID | null;
  weights: Record<string, number>;
  min_proximity: number;
  status: string;
  version: number;
  test_results: { tested_at?: string; tested_by?: string; pairs?: ProximityTestPair[] } | null;
  activated_at: ISODate | null;
  created_at: ISODate;
}

export interface ProximityTestPair {
  customer: string;
  competitor: string;
  score: number;
  mapped: boolean;
  rationale?: string;
  [k: string]: unknown;
}

export interface ModelsInfo {
  config: Record<string, string | number | boolean | null>;
  prompts: { id: string; version: string; hash: string }[];
  usage_30d: { workflow: string; model: string; status: string; calls: number; avg_latency_ms: number; cost_usd: number }[];
}

export interface TenantSettings {
  tenant: { id: UUID; name: string; slug: string; settings: { llm_monthly_budget_usd?: number; retention_days?: Record<string, number>; [k: string]: unknown } };
  allow_training_on_customer_data: boolean;
}

export interface Usage {
  window_days: number;
  budget_usd: number | null;
  items: { kind: string; component: string; model: string | null; input_units: number; output_units: number; cost_usd: number }[];
}

export interface AuditEntry {
  id: number;
  actor_id: string | null;
  actor_type: string;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  before: unknown;
  after: unknown;
  reason: string | null;
  request_id: string | null;
  ip: string | null;
  prev_hash: string;
  hash: string;
  created_at: ISODate;
}

export interface TuningSuggestion {
  current: Record<string, number>;
  current_metrics: Record<string, number | null>;
  suggested: Record<string, number> | null;
  suggested_metrics?: Record<string, number | null>;
  reason?: string;
  [k: string]: unknown;
}

export interface FeedbackDataset {
  id: UUID;
  name: string;
  version: number;
  record_count: number;
  content_hash: string;
  landscape_id: UUID | null;
  created_at: ISODate;
}

export interface ModelRelease {
  id: UUID;
  component: string;
  version: string;
  status: string;
  dataset_id: UUID;
  config: { landscape_id?: string; band_thresholds?: Record<string, number> };
  evaluation: Record<string, unknown>;
  promoted_by: string | null;
  promoted_at: ISODate | null;
  created_at: ISODate;
}

// ---------------------------------------------------------------- explainability (NIST IR 8312 principles)
export interface ScoreDriver {
  dimension: string;
  name: string;
  score: number;
  weight: number;
  contribution: number;
  reasons: string[];
}

export interface EventExplanation {
  principles: string[];
  summary: string;
  score: {
    method: string;
    formula?: string;
    version?: string;
    raw_score?: number;
    magnitude_gate: number;
    drivers: ScoreDriver[];
    sensitivity: { dimension: string; score_if_zero: number; delta: number }[];
    counterfactuals: string[];
    model_confidence?: string;
  };
  mapping: { asset: string; proximity: number; rationale: string; path: string[]; rule?: string;
    shared_dimensions: Record<string, { weight: number; score: number; shared?: string[] }> }[];
  evidence: { facts: number; facts_with_evidence: number; supported: number; withheld: number;
    validator?: string; independent_judge_used: boolean };
  generation: { ai_generated: boolean; human_edited: boolean; review_status: string; model: string | null;
    workflow: string | null; prompt_version: string | null; generation_id: string | null };
  knowledge_limits: string[];
}

export interface AnswerExplanation {
  principles: string[];
  steps: string[];
  knowledge_limits: string[];
  evidence_coverage: { facts: number; facts_with_evidence: number };
}

export interface TransparencyCard {
  system: string;
  purpose: string;
  not_intended_for: string[];
  components: { name: string; type: string; model?: string; explainability?: string }[];
  human_oversight: string[];
  data: { sources: string[]; customer_data_used_for_training: boolean };
  known_limitations: string[];
  evaluation: { suite: string; gate: string; metrics: string[] };
  prompts: { id: string; version: string; hash: string }[];
  xai_principles: string;
}
