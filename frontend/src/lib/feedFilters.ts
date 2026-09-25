import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { Query } from '../api/client';

/**
 * Feed filter state lives entirely in the URL query string (FR-UX-002): every view is bookmarkable
 * and shareable. Keys mirror GET /events query params; *_name keys are display labels only.
 */
export const MULTI_KEYS = ['band', 'event_type', 'source', 'status'] as const;
export const SINGLE_KEYS = [
  'landscape_id',
  'from',
  'to',
  'min_score',
  'company_id',
  'company_name',
  'asset_id',
  'asset_name',
  'impacted_asset_id',
  'mechanism',
  'indication',
  'q',
  'sort',
  'personalize',
  'offset',
] as const;

export type MultiKey = (typeof MULTI_KEYS)[number];
export type SingleKey = (typeof SINGLE_KEYS)[number];

export type FeedFilters = { [K in MultiKey]: string[] } & { [K in SingleKey]?: string };

export const PAGE_SIZE = 50;

export function emptyFilters(): FeedFilters {
  return { band: [], event_type: [], source: [], status: [] };
}

export function parseFeedParams(sp: URLSearchParams): FeedFilters {
  const f = emptyFilters();
  for (const k of MULTI_KEYS) f[k] = sp.getAll(k).filter(Boolean);
  for (const k of SINGLE_KEYS) {
    const v = sp.get(k);
    if (v !== null && v !== '') f[k] = v;
  }
  return f;
}

export function toSearchParams(f: FeedFilters): URLSearchParams {
  const sp = new URLSearchParams();
  for (const k of MULTI_KEYS) for (const v of f[k] ?? []) if (v) sp.append(k, v);
  for (const k of SINGLE_KEYS) {
    const v = f[k];
    if (v !== undefined && v !== '') sp.set(k, v);
  }
  return sp;
}

/** Map URL filters to the GET /events query (drops display-only keys, makes `to` inclusive). */
export function toApiQuery(f: FeedFilters, fallbackLandscapeId?: string): Query {
  const to = f.to && /^\d{4}-\d{2}-\d{2}$/.test(f.to) ? `${f.to}T23:59:59` : f.to;
  return {
    landscape_id: f.landscape_id ?? fallbackLandscapeId,
    from: f.from,
    to,
    min_score: f.min_score,
    band: f.band,
    event_type: f.event_type,
    source: f.source,
    status: f.status,
    company_id: f.company_id,
    asset_id: f.asset_id,
    impacted_asset_id: f.impacted_asset_id,
    mechanism: f.mechanism,
    indication: f.indication,
    q: f.q,
    sort: f.sort ?? 'date',
    personalize: f.personalize === 'true' ? true : undefined,
    limit: PAGE_SIZE,
    offset: f.offset ?? 0,
  };
}

export function activeFilterCount(f: FeedFilters): number {
  let n = 0;
  for (const k of MULTI_KEYS) n += f[k].length;
  for (const k of ['from', 'to', 'min_score', 'company_id', 'asset_id', 'impacted_asset_id', 'mechanism', 'indication', 'q', 'personalize'] as const) {
    if (f[k]) n += 1;
  }
  return n;
}

/** Filters as a plain object for saved views (arrays kept, empties dropped). */
export function filtersToObject(f: FeedFilters): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {};
  for (const [k, v] of toSearchParams({ ...f, offset: undefined }).entries()) {
    const prev = out[k];
    if ((MULTI_KEYS as readonly string[]).includes(k)) out[k] = [...((prev as string[] | undefined) ?? []), v];
    else out[k] = v;
  }
  return out;
}

export function objectToFilters(o: Record<string, unknown>): FeedFilters {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) {
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)));
    else if (v !== null && v !== undefined && v !== '') sp.set(k, String(v));
  }
  return parseFeedParams(sp);
}

export function useFeedFilters(): [FeedFilters, (patch: Partial<FeedFilters>, opts?: { replace?: boolean }) => void, () => void] {
  const [sp, setSp] = useSearchParams();
  const filters = useMemo(() => parseFeedParams(sp), [sp]);
  const update = useCallback(
    (patch: Partial<FeedFilters>, opts?: { replace?: boolean }) => {
      setSp(
        (prev) => {
          const cur = parseFeedParams(prev);
          const next: FeedFilters = { ...cur, ...patch } as FeedFilters;
          // Any filter change returns to the first page unless the patch sets the offset itself.
          if (!('offset' in patch)) next.offset = undefined;
          return toSearchParams(next);
        },
        { replace: opts?.replace },
      );
    },
    [setSp],
  );
  const reset = useCallback(() => setSp(new URLSearchParams()), [setSp]);
  return [filters, update, reset];
}
