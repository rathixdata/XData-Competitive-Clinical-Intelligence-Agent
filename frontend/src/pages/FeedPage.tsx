import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bookmark, Filter, Link2, RotateCcw, Trash2, X } from 'lucide-react';
import { api } from '../api/endpoints';
import { BANDS, type SavedView, type Visibility } from '../api/types';
import { BandBadge, ReviewBadge, StatusBadge } from '../components/Badges';
import { Modal } from '../components/Dialog';
import { EntityPicker } from '../components/EntityPicker';
import { EmptyState, ErrorState, InlineError, Loading } from '../components/States';
import { useLandscape } from '../state/landscapeContext';
import {
  activeFilterCount,
  filtersToObject,
  objectToFilters,
  PAGE_SIZE,
  toApiQuery,
  useFeedFilters,
  type FeedFilters,
  type MultiKey,
} from '../lib/feedFilters';
import { fmtDate, humanize } from '../lib/format';
import { errorMessage, useToast } from '../lib/toastContext';

const STATUS_OPTIONS = ['published', 'acknowledged', 'escalated', 'blocked', 'archived'];
const SORTS: { value: string; label: string }[] = [
  { value: 'date', label: 'Newest first' },
  { value: '-date', label: 'Oldest first' },
  { value: 'score', label: 'Highest materiality' },
  { value: '-score', label: 'Lowest materiality' },
];

function CheckGroup({
  legend,
  options,
  selected,
  onChange,
  render,
}: {
  legend: string;
  options: { value: string; count?: number }[];
  selected: string[];
  onChange: (v: string[]) => void;
  render?: (v: string) => ReactNode;
}) {
  return (
    <fieldset>
      <legend>{legend}</legend>
      <div className="stack-sm" style={{ gap: 4, maxHeight: 180, overflowY: 'auto' }}>
        {options.length === 0 ? <span className="small muted">No options</span> : null}
        {options.map((o) => (
          <label key={o.value} className="checkbox">
            <input
              type="checkbox"
              checked={selected.includes(o.value)}
              onChange={(e) => onChange(e.target.checked ? [...selected, o.value] : selected.filter((x) => x !== o.value))}
            />
            {render ? render(o.value) : humanize(o.value)}
            {o.count !== undefined ? <span className="tiny muted">({o.count})</span> : null}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function TextFilters({ filters, update }: { filters: FeedFilters; update: (p: Partial<FeedFilters>) => void }) {
  const [draft, setDraft] = useState({ q: filters.q ?? '', from: filters.from ?? '', to: filters.to ?? '', min_score: filters.min_score ?? '' });
  useEffect(() => {
    setDraft({ q: filters.q ?? '', from: filters.from ?? '', to: filters.to ?? '', min_score: filters.min_score ?? '' });
  }, [filters.q, filters.from, filters.to, filters.min_score]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    update({ q: draft.q || undefined, from: draft.from || undefined, to: draft.to || undefined, min_score: draft.min_score || undefined });
  };
  return (
    <form className="form-grid" onSubmit={submit} aria-label="Search and range filters">
      <div className="field" style={{ gridColumn: 'span 2' }}>
        <label htmlFor="f-q">Search titles</label>
        <input id="f-q" type="search" value={draft.q} onChange={(e) => setDraft({ ...draft, q: e.target.value })} placeholder="e.g. NCT99000001, endpoint" />
      </div>
      <div className="field">
        <label htmlFor="f-from">Detected from</label>
        <input id="f-from" type="date" value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="f-to">Detected to</label>
        <input id="f-to" type="date" value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="f-min">Minimum score</label>
        <input id="f-min" type="number" min={0} max={100} step={1} value={draft.min_score} onChange={(e) => setDraft({ ...draft, min_score: e.target.value })} />
      </div>
      <div className="field">
        <button type="submit" className="btn btn-primary">
          Apply
        </button>
      </div>
    </form>
  );
}

function SavedViews({ filters, update }: { filters: FeedFilters; update: (p: Partial<FeedFilters>) => void }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const views = useQuery({ queryKey: ['saved-views', 'feed'], queryFn: () => api.savedViews('feed') });
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [visibility, setVisibility] = useState<Visibility>('private');
  const create = useMutation({
    mutationFn: () => api.createSavedView({ name, view: 'feed', filters: filtersToObject(filters), visibility }),
    onSuccess: () => {
      setOpen(false);
      setName('');
      notify('View saved');
      void qc.invalidateQueries({ queryKey: ['saved-views'] });
    },
  });
  const del = useMutation({
    mutationFn: (id: string) => api.deleteSavedView(id),
    onSuccess: () => {
      notify('View deleted');
      void qc.invalidateQueries({ queryKey: ['saved-views'] });
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  const apply = (v: SavedView) => {
    const f = objectToFilters(v.filters);
    // Replace every key (so filters absent from the view are cleared).
    update({ ...Object.fromEntries(Object.keys(filters).map((k) => [k, undefined])), ...f });
  };
  const items = views.data?.items ?? [];
  return (
    <div className="row">
      <label htmlFor="saved-view" className="small strong">
        Saved views
      </label>
      <select
        id="saved-view"
        style={{ width: 220 }}
        value=""
        onChange={(e) => {
          const v = items.find((x) => x.id === e.target.value);
          if (v) apply(v);
        }}
      >
        <option value="">{items.length ? 'Apply a saved view...' : 'No saved views'}</option>
        {items.map((v) => (
          <option key={v.id} value={v.id}>
            {v.name} ({v.visibility}
            {v.owned ? '' : ', shared'})
          </option>
        ))}
      </select>
      <button type="button" className="btn btn-sm" onClick={() => setOpen(true)}>
        <Bookmark size={14} aria-hidden /> Save view
      </button>
      <button
        type="button"
        className="btn btn-sm"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(window.location.href);
            notify('Link to this view copied');
          } catch {
            notify('Copy failed - copy the address bar URL instead', 'error');
          }
        }}
      >
        <Link2 size={14} aria-hidden /> Copy link
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Save feed view"
        footer={
          <>
            <button type="button" className="btn" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button type="submit" form="save-view-form" className="btn btn-primary" disabled={!name.trim() || create.isPending}>
              Save
            </button>
          </>
        }
      >
        <form
          id="save-view-form"
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <InlineError error={create.error} />
          <div className="field">
            <label htmlFor="sv-name">Name</label>
            <input id="sv-name" type="text" required value={name} onChange={(e) => setName(e.target.value)} data-autofocus />
          </div>
          <div className="field">
            <label htmlFor="sv-vis">Visibility</label>
            <select id="sv-vis" value={visibility} onChange={(e) => setVisibility(e.target.value as Visibility)}>
              <option value="private">Private (only me)</option>
              <option value="team">Team</option>
              <option value="tenant">Everyone in the tenant</option>
            </select>
          </div>
          <p className="small muted">Saves the current filters: {activeFilterCount(filters)} active, sort {filters.sort ?? 'date'}.</p>
          {items.filter((v) => v.owned).length ? (
            <div>
              <h3>Your saved views</h3>
              <ul className="list-plain">
                {items
                  .filter((v) => v.owned)
                  .map((v) => (
                    <li key={v.id} className="row-between">
                      <span>
                        {v.name} <span className="badge badge-neutral">{v.visibility}</span>
                      </span>
                      <button type="button" className="btn btn-sm btn-ghost" onClick={() => del.mutate(v.id)} aria-label={`Delete saved view ${v.name}`}>
                        <Trash2 size={14} aria-hidden />
                      </button>
                    </li>
                  ))}
              </ul>
            </div>
          ) : null}
        </form>
      </Modal>
    </div>
  );
}

export function FeedPage() {
  const [filters, update, reset] = useFeedFilters();
  const { landscapeId } = useLandscape();
  const lsId = filters.landscape_id ?? landscapeId;
  const [showFilters, setShowFilters] = useState(true);
  const facets = useQuery({ queryKey: ['facets', lsId ?? null], queryFn: () => api.facets(lsId), staleTime: 5 * 60_000 });
  const lsDetail = useQuery({ queryKey: ['landscape', lsId], queryFn: () => api.landscape(lsId as string), enabled: Boolean(lsId), staleTime: 60_000 });
  const apiQuery = toApiQuery(filters, landscapeId);
  const events = useQuery({ queryKey: ['events', apiQuery], queryFn: () => api.events(apiQuery), placeholderData: keepPreviousData });

  const fc = facets.data ?? {};
  const customers = (lsDetail.data?.members ?? []).filter((m) => m.role === 'customer' && m.entity_type === 'asset');
  const setMulti = (k: MultiKey) => (v: string[]) => update({ [k]: v } as Partial<FeedFilters>);
  const offset = Number(filters.offset ?? 0);
  const count = activeFilterCount(filters);

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Intelligence feed</h1>
          <p>Every filter is part of the page address, so any view can be bookmarked or shared.</p>
        </div>
        <SavedViews filters={filters} update={update} />
      </div>

      <section className="card" aria-labelledby="filters-h" style={{ marginBottom: 16 }}>
        <div className="card-header">
          <h2 id="filters-h" className="row">
            <Filter size={16} aria-hidden /> Filters {count ? <span className="badge badge-info">{count} active</span> : null}
          </h2>
          <div className="row">
            <label htmlFor="f-sort" className="small strong">
              Sort
            </label>
            <select id="f-sort" style={{ width: 190 }} value={filters.sort ?? 'date'} onChange={(e) => update({ sort: e.target.value })}>
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
            <label className="checkbox">
              <input type="checkbox" checked={filters.personalize === 'true'} onChange={(e) => update({ personalize: e.target.checked ? 'true' : undefined })} />
              Personalise ranking (watchlists)
            </label>
            <button type="button" className="btn btn-sm" onClick={reset} disabled={count === 0 && !filters.sort}>
              <RotateCcw size={14} aria-hidden /> Reset
            </button>
            <button type="button" className="btn btn-sm" aria-expanded={showFilters} aria-controls="filter-body" onClick={() => setShowFilters((s) => !s)}>
              {showFilters ? 'Hide filters' : 'Show filters'}
            </button>
          </div>
        </div>
        <div id="filter-body" hidden={!showFilters} className="stack">
          <TextFilters filters={filters} update={update} />
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))' }}>
            <CheckGroup
              legend="Band"
              options={BANDS.map((b) => ({ value: b }))}
              selected={filters.band}
              onChange={setMulti('band')}
              render={(v) => <BandBadge band={v} />}
            />
            <CheckGroup legend="Event type" options={fc.type ?? []} selected={filters.event_type} onChange={setMulti('event_type')} />
            <CheckGroup legend="Source" options={fc.source ?? []} selected={filters.source} onChange={setMulti('source')} render={(v) => v} />
            <CheckGroup legend="Status" options={STATUS_OPTIONS.map((s) => ({ value: s }))} selected={filters.status} onChange={setMulti('status')} />
            <div className="stack-sm">
              <div className="field">
                <label htmlFor="f-mech">Mechanism</label>
                <select id="f-mech" value={filters.mechanism ?? ''} onChange={(e) => update({ mechanism: e.target.value || undefined })}>
                  <option value="">Any mechanism</option>
                  {[...(fc.mechanism ?? []), ...(fc.target ?? [])].map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.value} ({m.count})
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="f-ind">Indication</label>
                <select id="f-ind" value={filters.indication ?? ''} onChange={(e) => update({ indication: e.target.value || undefined })}>
                  <option value="">Any indication</option>
                  {(fc.indication ?? []).map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.value} ({m.count})
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="f-imp">Affects my asset</label>
                <select id="f-imp" value={filters.impacted_asset_id ?? ''} onChange={(e) => update({ impacted_asset_id: e.target.value || undefined })}>
                  <option value="">Any</option>
                  {customers.map((m) => (
                    <option key={m.entity_id} value={m.entity_id}>
                      {m.label ?? m.entity_id}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="stack-sm">
              <EntityPicker label="Company" type="company" onSelect={(h) => update({ company_id: h.id, company_name: h.name })} />
              {filters.company_id ? (
                <span className="badge badge-info">
                  Company: {filters.company_name ?? filters.company_id.slice(0, 8)}
                  <button type="button" className="btn btn-ghost btn-sm" style={{ height: 18 }} onClick={() => update({ company_id: undefined, company_name: undefined })} aria-label="Clear company filter">
                    <X size={12} aria-hidden />
                  </button>
                </span>
              ) : null}
              <EntityPicker label="Competitor asset" type="asset" onSelect={(h) => update({ asset_id: h.id, asset_name: h.name })} />
              {filters.asset_id ? (
                <span className="badge badge-info">
                  Asset: {filters.asset_name ?? filters.asset_id.slice(0, 8)}
                  <button type="button" className="btn btn-ghost btn-sm" style={{ height: 18 }} onClick={() => update({ asset_id: undefined, asset_name: undefined })} aria-label="Clear asset filter">
                    <X size={12} aria-hidden />
                  </button>
                </span>
              ) : null}
            </div>
          </div>
        </div>
      </section>

      <section aria-labelledby="results-h">
        <div className="row-between" style={{ marginBottom: 8 }}>
          <h2 id="results-h" style={{ margin: 0 }}>
            Results
          </h2>
          <span className="small muted" aria-live="polite">
            {events.data ? `${events.data.total} event${events.data.total === 1 ? '' : 's'}` : ''}
            {events.isFetching && !events.isLoading ? ' - updating...' : ''}
          </span>
        </div>
        {events.isLoading ? (
          <Loading label="Loading events" />
        ) : events.error ? (
          <ErrorState error={events.error} onRetry={() => void events.refetch()} />
        ) : !events.data || events.data.items.length === 0 ? (
          <div className="card">
            <EmptyState title="No events match these filters">
              <button type="button" className="btn btn-sm" onClick={reset}>
                Clear filters
              </button>
            </EmptyState>
          </div>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <caption className="sr-only">Intelligence events</caption>
                <thead>
                  <tr>
                    <th scope="col">Materiality</th>
                    <th scope="col">Event</th>
                    <th scope="col">Type</th>
                    <th scope="col">Affected asset(s)</th>
                    <th scope="col">Source</th>
                    <th scope="col">Status</th>
                    <th scope="col">Review</th>
                    <th scope="col">Detected</th>
                  </tr>
                </thead>
                <tbody>
                  {events.data.items.map((e) => (
                    <tr key={e.id}>
                      <td>
                        <BandBadge band={e.band} score={e.materiality_score} />
                        {e.personal_boost ? <div className="tiny muted">+{e.personal_boost} watchlist boost</div> : null}
                      </td>
                      <td style={{ minWidth: 260 }}>
                        <Link to={`/events/${e.id}`}>{e.title}</Link>
                        {e.update_summary?.length ? <div className="tiny muted">Updated: {e.update_summary.join('; ')}</div> : null}
                      </td>
                      <td>{humanize(e.primary_type)}</td>
                      <td>{e.impacted_assets?.length ? [...new Set(e.impacted_assets.map((m) => m.asset_name))].join(', ') : <span className="muted">None mapped</span>}</td>
                      <td>{e.source}</td>
                      <td>
                        <StatusBadge status={e.status} />
                      </td>
                      <td>
                        <ReviewBadge status={e.review_status} />
                      </td>
                      <td className="nowrap">{fmtDate(e.detected_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <nav className="row-between" aria-label="Pagination" style={{ marginTop: 10 }}>
              <span className="small muted">
                Showing {offset + 1}-{offset + events.data.items.length} of {events.data.total}
              </span>
              <div className="btn-group">
                <button type="button" className="btn btn-sm" disabled={offset === 0} onClick={() => update({ offset: offset - PAGE_SIZE > 0 ? String(offset - PAGE_SIZE) : undefined })}>
                  Previous
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={events.data.next_offset === null}
                  onClick={() => update({ offset: String(events.data?.next_offset ?? 0) })}
                >
                  Next
                </button>
              </div>
            </nav>
          </>
        )}
      </section>
    </>
  );
}

