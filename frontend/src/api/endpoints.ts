import { download, request, type Query } from './client';
import type {
  TransparencyCard,
  AlertPolicy,
  AlertPolicyInput,
  AlertPreview,
  Artifact,
  AskSession,
  AskSessionDetail,
  AssetDetail,
  AuditEntry,
  Asset,
  CatalystResponse,
  Comparison,
  ConnectorHealth,
  ConnectorRun,
  Dashboard,
  EntityLink,
  EntitySearchHit,
  EventDetail,
  EvidenceContext,
  FeedbackDataset,
  FeedbackLabel,
  Facets,
  Graph,
  IntelEvent,
  KPIs,
  Landscape,
  LandscapeDetail,
  Matrix,
  Me,
  ModelRelease,
  ModelsInfo,
  Notification,
  Paged,
  ProfileField,
  ProfileVersion,
  ProximityRule,
  ProximityTestPair,
  Report,
  ReportDetail,
  SavedView,
  Statement,
  Template,
  TenantSettings,
  TuningSuggestion,
  Usage,
  User,
  Visibility,
  Watchlist,
  WatchlistDetail,
} from './types';

export type ExportFormat = 'docx' | 'pdf' | 'pptx' | 'md';

const enc = encodeURIComponent;

export const api = {
  // ---------------------------------------------------------------- auth
  me: () => request<Me>('/auth/me'),

  // ---------------------------------------------------------------- portfolio
  dashboard: (landscapeId?: string) => request<Dashboard>('/dashboard', { query: { landscape_id: landscapeId } }),
  catalysts: (q: { from?: string; to?: string; landscape_id?: string; basis?: string; changed_only?: boolean; asset_id?: string }) =>
    request<CatalystResponse>('/catalysts', { query: q }),
  compare: (assetIds: string[]) => request<Comparison>('/comparisons', { method: 'POST', body: { asset_ids: assetIds } }),
  compareExport: (assetIds: string[], format: ExportFormat) =>
    download('/comparisons/export', `xdata-comparison.${format}`, { method: 'POST', query: { format }, body: { asset_ids: assetIds } }),
  kpis: (landscapeId?: string, days = 90) => request<KPIs>('/kpis', { query: { landscape_id: landscapeId, days } }),

  // ---------------------------------------------------------------- events
  events: (q: Query) => request<Paged<IntelEvent>>('/events', { query: q }),
  facets: (landscapeId?: string) => request<Facets>('/events/facets', { query: { landscape_id: landscapeId } }),
  event: (id: string) => request<EventDetail>(`/events/${enc(id)}`),
  aiTransparency: () => request<TransparencyCard>('/auth/ai-transparency'),
  acknowledge: (id: string, note?: string) =>
    request<IntelEvent>(`/events/${enc(id)}/acknowledge`, { method: 'POST', body: { note: note || null } }),
  escalate: (id: string, note?: string) =>
    request<IntelEvent>(`/events/${enc(id)}/escalate`, { method: 'POST', body: { note: note || null } }),
  review: (id: string, action: 'approve' | 'request_changes', note?: string) =>
    request<IntelEvent>(`/events/${enc(id)}/review`, { method: 'POST', body: { action, note: note || null } }),
  regenerate: (id: string) => request<Artifact>(`/events/${enc(id)}/regenerate`, { method: 'POST' }),
  editNarrative: (id: string, body: { headline?: string | null; statements: Statement[]; reason: string }) =>
    request<Artifact>(`/events/${enc(id)}/narrative`, { method: 'PUT', body }),
  artifact: (eventId: string, artifactId: string) => request<Artifact>(`/events/${enc(eventId)}/artifacts/${enc(artifactId)}`),
  feedback: (body: { intel_event_id: string; label: FeedbackLabel; reason?: string; comment?: string; claim_id?: string }) =>
    request<unknown>('/feedback', { method: 'POST', body }),

  // ---------------------------------------------------------------- sources
  evidenceContext: (chunkId: string, window = 1) =>
    request<EvidenceContext>(`/sources/chunks/${enc(chunkId)}`, { query: { window } }),

  // ---------------------------------------------------------------- landscapes
  landscapes: () => request<Landscape[]>('/landscapes'),
  landscape: (id: string) => request<LandscapeDetail>(`/landscapes/${enc(id)}`),
  createLandscape: (body: {
    name: string;
    description?: string;
    disease?: string;
    geographies?: string[];
    template_id?: string | null;
    config?: Record<string, unknown>;
    members?: { entity_type: string; entity_id: string; role: string }[];
  }) => request<Landscape>('/landscapes', { method: 'POST', body, headers: { 'Idempotency-Key': newId() } }),
  patchLandscape: (id: string, body: Record<string, unknown>) =>
    request<Landscape>(`/landscapes/${enc(id)}`, { method: 'PATCH', body }),
  putThresholds: (
    id: string,
    body: { band_thresholds?: Record<string, number>; materiality_weights?: Record<string, number>; reason?: string },
  ) => request<Landscape>(`/landscapes/${enc(id)}/thresholds`, { method: 'PUT', body }),
  addMembers: (id: string, members: { entity_type: string; entity_id: string; role: string }[]) =>
    request<{ added: number }>(`/landscapes/${enc(id)}/members`, { method: 'POST', body: members }),
  removeMember: (id: string, entityId: string) =>
    request<void>(`/landscapes/${enc(id)}/members/${enc(entityId)}`, { method: 'DELETE' }),
  matrix: (id: string) => request<Matrix>(`/landscapes/${enc(id)}/matrix`),
  graph: (id: string, depth = 1) => request<Graph>(`/landscapes/${enc(id)}/graph`, { query: { depth } }),
  exportLandscape: (id: string) => request<unknown>(`/landscapes/${enc(id)}/export`),
  templates: () => request<Template[]>('/templates'),

  // ---------------------------------------------------------------- watchlists / views
  watchlists: () => request<Watchlist[]>('/watchlists'),
  watchlist: (id: string) => request<WatchlistDetail>(`/watchlists/${enc(id)}`),
  createWatchlist: (body: { name: string; description?: string; visibility: Visibility; landscape_id?: string | null }) =>
    request<Watchlist>('/watchlists', { method: 'POST', body }),
  patchWatchlist: (id: string, body: Partial<Pick<Watchlist, 'name' | 'description' | 'visibility'>>) =>
    request<Watchlist>(`/watchlists/${enc(id)}`, { method: 'PATCH', body }),
  deleteWatchlist: (id: string) => request<void>(`/watchlists/${enc(id)}`, { method: 'DELETE' }),
  addWatchItems: (id: string, items: { item_type: string; entity_id?: string | null; value: string }[]) =>
    request<{ added: number }>(`/watchlists/${enc(id)}/items`, { method: 'POST', body: items }),
  removeWatchItem: (id: string, itemId: string) =>
    request<void>(`/watchlists/${enc(id)}/items/${enc(itemId)}`, { method: 'DELETE' }),
  importWatchlist: (id: string, csv: string) =>
    request<{ added: number; unresolved: { row: Record<string, string>; error: string; candidates?: unknown[] }[] }>(
      `/watchlists/${enc(id)}/import`,
      { method: 'POST', rawBody: csv, contentType: 'text/csv' },
    ),
  savedViews: (view?: string) => request<Paged<SavedView>>('/saved-views', { query: { view, limit: 200 } }),
  createSavedView: (body: { name: string; view: SavedView['view']; filters: Record<string, unknown>; visibility: Visibility }) =>
    request<SavedView>('/saved-views', { method: 'POST', body }),
  deleteSavedView: (id: string) => request<void>(`/saved-views/${enc(id)}`, { method: 'DELETE' }),

  // ---------------------------------------------------------------- entities / assets
  searchEntities: (q: string, type?: string, limit = 20) =>
    request<EntitySearchHit[]>('/entities/search', { query: { q, type, limit } }),
  reviewQueue: (q: { status?: string; entity_type?: string; offset?: number; limit?: number }) =>
    request<Paged<EntityLink>>('/entities/review', { query: q }),
  decideReview: (id: string, body: { decision: 'approve' | 'reject'; entity_id?: string | null; reason?: string }) =>
    request<EntityLink>(`/entities/review/${enc(id)}`, { method: 'POST', body: { ...body, scope: 'tenant' } }),
  addAlias: (type: string, id: string, body: { alias: string; alias_type: string; reason?: string }) =>
    request<unknown>(`/entities/${enc(type)}/${enc(id)}/aliases`, { method: 'POST', body }),
  mergeEntities: (body: { entity_type: string; source_id: string; target_id: string; reason: string }) =>
    request<{ merged: string; into: string }>('/entities/merge', { method: 'POST', body }),
  splitEntity: (body: { entity_type: string; entity_id: string; new_name: string; alias_ids: string[]; reason: string }) =>
    request<{ new_entity_id: string; aliases_moved: number }>('/entities/split', { method: 'POST', body }),
  entity: (type: string, id: string) =>
    request<{ entity: Record<string, unknown>; type: string; aliases: { id: string; alias: string; alias_type: string; tenant_id: string | null }[] }>(
      `/entities/${enc(type)}/${enc(id)}`,
    ),
  assets: (q: { q?: string; internal?: boolean; limit?: number; offset?: number }) => request<Paged<Asset>>('/assets', { query: q }),
  asset: (id: string) => request<AssetDetail>(`/assets/${enc(id)}`),
  profileVersions: (id: string) => request<ProfileVersion[]>(`/assets/${enc(id)}/profile/versions`),
  profileFields: () => request<ProfileField[]>('/profile-fields'),
  patchProfile: (id: string, profile: Record<string, unknown>, reason?: string) =>
    request<Asset>(`/assets/${enc(id)}/profile`, { method: 'PATCH', body: { profile, reason: reason || null } }),

  // ---------------------------------------------------------------- ask
  askSessions: () => request<AskSession[]>('/ask/sessions'),
  askSession: (id: string) => request<AskSessionDetail>(`/ask/sessions/${enc(id)}`),
  askExport: (artifactId: string, format: ExportFormat) =>
    download(`/ask/answers/${enc(artifactId)}/export`, `xdata-answer.${format}`, { query: { format } }),

  // ---------------------------------------------------------------- reports
  reports: (landscapeId?: string) => request<Report[]>('/reports', { query: { landscape_id: landscapeId } }),
  report: (id: string) => request<ReportDetail>(`/reports/${enc(id)}`),
  createBrief: (body: { landscape_id: string; period_start?: string; period_end?: string }) =>
    request<ReportDetail>('/reports/briefs', { method: 'POST', body }),
  editReport: (
    id: string,
    body: { executive_summary?: string; top_developments?: { event_id: string; headline: string; so_what: string }[]; watch_items?: string[]; reason: string },
  ) => request<ReportDetail>(`/reports/${enc(id)}`, { method: 'PATCH', body }),
  approveReport: (id: string) => request<Report>(`/reports/${enc(id)}/approve`, { method: 'POST' }),
  distributeReport: (id: string, list: string[]) =>
    request<Report>(`/reports/${enc(id)}/distribute`, { method: 'POST', body: { distribution_list: list } }),
  exportReport: (id: string, format: ExportFormat) =>
    download(`/reports/${enc(id)}/export`, `xdata-brief.${format}`, { query: { format } }),

  // ---------------------------------------------------------------- alerts
  policies: () => request<AlertPolicy[]>('/alerts/policies'),
  createPolicy: (body: AlertPolicyInput) => request<AlertPolicy>('/alerts/policies', { method: 'POST', body }),
  updatePolicy: (id: string, body: AlertPolicyInput) => request<AlertPolicy>(`/alerts/policies/${enc(id)}`, { method: 'PUT', body }),
  deletePolicy: (id: string) => request<void>(`/alerts/policies/${enc(id)}`, { method: 'DELETE' }),
  previewPolicy: (body: Partial<AlertPolicyInput> & { days?: number }) =>
    request<AlertPreview>('/alerts/policies/preview', { method: 'POST', body }),
  testPolicy: (id: string) => request<{ results: Record<string, string> }>(`/alerts/policies/${enc(id)}/test`, { method: 'POST' }),
  deliveries: (q: { status?: string; channel?: string; offset?: number; limit?: number }) =>
    request<Paged<Notification>>('/alerts/deliveries', { query: q }),
  inbox: (unreadOnly = false) => request<Notification[]>('/alerts/inbox', { query: { unread_only: unreadOnly || undefined } }),
  markRead: (id: string) => request<Notification>(`/alerts/inbox/${enc(id)}/read`, { method: 'POST' }),

  // ---------------------------------------------------------------- admin
  connectors: () => request<ConnectorHealth[]>('/admin/connectors'),
  runConnector: (key: string) => request<{ queued: boolean; task_id: string }>(`/admin/connectors/${enc(key)}/run`, { method: 'POST' }),
  connectorRuns: (key: string, offset = 0) =>
    request<Paged<ConnectorRun>>(`/admin/connectors/${enc(key)}/runs`, { query: { limit: 20, offset } }),
  users: () => request<User[]>('/admin/users'),
  createUser: (body: { email: string; display_name: string; roles: string[]; team?: string; password?: string }) =>
    request<User>('/admin/users', { method: 'POST', body }),
  patchUser: (id: string, body: { roles?: string[]; team?: string; is_active?: boolean; display_name?: string }) =>
    request<User>(`/admin/users/${enc(id)}`, { method: 'PATCH', body }),
  roles: () => request<Record<string, string[]>>('/admin/roles'),
  proximityRules: () => request<ProximityRule[]>('/admin/proximity-rules'),
  createProximityRule: (body: { name: string; landscape_id?: string | null; weights: Record<string, number>; min_proximity: number }) =>
    request<ProximityRule>('/admin/proximity-rules', { method: 'POST', body }),
  testProximityRule: (id: string) =>
    request<{ tested_at: string; pairs: ProximityTestPair[] }>(`/admin/proximity-rules/${enc(id)}/test`, { method: 'POST', body: {} }),
  activateProximityRule: (id: string) => request<ProximityRule>(`/admin/proximity-rules/${enc(id)}/activate`, { method: 'POST' }),
  models: () => request<ModelsInfo>('/admin/models'),
  settings: () => request<TenantSettings>('/admin/settings'),
  patchSettings: (body: { llm_monthly_budget_usd?: number; retention_days?: Record<string, number> }) =>
    request<unknown>('/admin/settings', { method: 'PATCH', body }),
  usage: (days = 30) => request<Usage>('/admin/usage', { query: { days } }),
  audit: (q: Query) => request<Paged<AuditEntry>>('/audit', { query: q }),
  auditExport: (format: 'csv' | 'json', q: Query) => download('/audit/export', `audit.${format}`, { query: { ...q, format } }),
  auditVerify: () => request<{ valid: boolean; checked: number; broken_at?: number | null; [k: string]: unknown }>('/audit/verify'),
  tuning: (landscapeId: string) =>
    request<TuningSuggestion>('/feedback/tuning-suggestions', { query: { landscape_id: landscapeId } }),
  datasets: () => request<FeedbackDataset[]>('/feedback/datasets'),
  createDataset: (body: { name: string; landscape_id?: string | null }) =>
    request<FeedbackDataset>('/feedback/datasets', { method: 'POST', body }),
  releases: () => request<ModelRelease[]>('/model-releases'),
  createRelease: (body: { landscape_id: string; dataset_id: string; band_thresholds: Record<string, number>; version: string }) =>
    request<ModelRelease>('/model-releases', { method: 'POST', body }),
  promoteRelease: (id: string) => request<ModelRelease>(`/model-releases/${enc(id)}/promote`, { method: 'POST' }),
};

function newId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}
