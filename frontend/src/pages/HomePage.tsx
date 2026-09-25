import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Activity, ArrowRight, CalendarDays, Star } from 'lucide-react';
import { api } from '../api/endpoints';
import { BANDS } from '../api/types';
import { BandBadge, BasisBadge, ChangedDateBadge, ReviewBadge, StatusBadge } from '../components/Badges';
import { EmptyState, QueryView } from '../components/States';
import { useLandscape } from '../state/landscapeContext';
import { fmtRelative, humanize } from '../lib/format';
import { catalystDate, previousDate } from '../lib/catalyst';

export function HomePage() {
  const { landscapeId, landscape } = useLandscape();
  const q = useQuery({ queryKey: ['dashboard', landscapeId ?? null], queryFn: () => api.dashboard(landscapeId), staleTime: 60_000 });

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Portfolio</h1>
          <p>{landscape ? `What changed in ${landscape.name}, and whether it matters to your assets.` : 'Your portfolio at a glance.'}</p>
        </div>
        <Link to="/feed" className="btn btn-primary">
          Open intelligence feed <ArrowRight size={15} aria-hidden />
        </Link>
      </div>
      <QueryView query={q} loadingLabel="Loading portfolio">
        {(d) => (
          <div className="stack" style={{ gap: 16 }}>
            <section className="card" aria-labelledby="bands-h">
              <div className="card-header">
                <h2 id="bands-h">Developments by materiality band (last 30 days)</h2>
              </div>
              <ul className="row list-plain" style={{ gap: 10 }}>
                {BANDS.slice()
                  .reverse()
                  .map((b) => (
                    <li key={b} style={{ padding: 0, border: 0 }}>
                      <Link to={`/feed?band=${encodeURIComponent(b)}`} className="btn" aria-label={`${d.band_counts_30d[b] ?? 0} ${b} events - open in feed`}>
                        <BandBadge band={b} />
                        <span className="score">{d.band_counts_30d[b] ?? 0}</span>
                      </Link>
                    </li>
                  ))}
              </ul>
            </section>

            <section aria-labelledby="assets-h">
              <h2 id="assets-h">Your assets</h2>
              {d.assets.length === 0 ? (
                <div className="card">
                  <EmptyState title="No customer assets in this landscape">Add an internal asset as a landscape member with role customer.</EmptyState>
                </div>
              ) : (
                <div className="grid grid-auto">
                  {d.assets.map((a) => (
                    <article key={a.asset_id} className="card stack-sm">
                      <div className="row-between">
                        <h3 style={{ margin: 0 }}>
                          <Link to={`/assets/${a.asset_id}`}>{a.name}</Link>
                        </h3>
                        {a.stage ? <span className="badge badge-neutral">{a.stage}</span> : null}
                      </div>
                      <p className="small muted" style={{ margin: 0 }}>
                        {[a.profile?.mechanism, a.profile?.population].filter(Boolean).map(String).join(' - ') || 'No profile details'}
                      </p>
                      <dl className="kv small">
                        <dt>Open high-priority</dt>
                        <dd>
                          <strong>{a.open_high_priority}</strong>
                        </dd>
                        <dt>Events (30 days)</dt>
                        <dd>{a.events_30d}</dd>
                      </dl>
                      <Link to={`/feed?impacted_asset_id=${a.asset_id}&sort=score`} className="small">
                        Developments affecting {a.name} <ArrowRight size={12} aria-hidden />
                      </Link>
                    </article>
                  ))}
                </div>
              )}
            </section>

            <div className="grid grid-main-side">
              <section className="card" aria-labelledby="dev-h">
                <div className="card-header">
                  <h2 id="dev-h">Material developments</h2>
                  <Link to="/feed?min_score=50&sort=score" className="small">
                    View all
                  </Link>
                </div>
                {d.material_developments.length === 0 ? (
                  <EmptyState title="No material developments in the last 30 days" />
                ) : (
                  <ul className="list-plain">
                    {d.material_developments.map((e) => (
                      <li key={e.id} className="stack-sm">
                        <div className="row">
                          <BandBadge band={e.band} score={e.materiality_score} />
                          <span className="badge badge-neutral">{humanize(e.primary_type)}</span>
                          <StatusBadge status={e.status} />
                          <ReviewBadge status={e.review_status} />
                        </div>
                        <Link to={`/events/${e.id}`} className="strong">
                          {e.title}
                        </Link>
                        <div className="small muted">
                          Detected {fmtRelative(e.detected_at)}
                          {e.impacted_assets?.length ? ` - may affect ${[...new Set(e.impacted_assets.map((m) => m.asset_name))].join(', ')}` : ''}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <div className="stack" style={{ gap: 16 }}>
                <section className="card" aria-labelledby="cat-h">
                  <div className="card-header">
                    <h2 id="cat-h">
                      <CalendarDays size={16} aria-hidden /> Upcoming catalysts (90 days)
                    </h2>
                    <Link to="/calendar" className="small">
                      Calendar
                    </Link>
                  </div>
                  {d.upcoming_catalysts.length === 0 ? (
                    <EmptyState title="No catalysts in the next 90 days" />
                  ) : (
                    <ul className="list-plain">
                      {d.upcoming_catalysts.map((c) => (
                        <li key={c.id} className="stack-sm">
                          <div className="row">
                            <span className="strong nowrap">{catalystDate(c)}</span>
                            <BasisBadge basis={c.date_basis} />
                            {c.history?.length ? <ChangedDateBadge previous={previousDate(c.history[c.history.length - 1])} /> : null}
                          </div>
                          <span className="small">{c.title}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section className="card" aria-labelledby="health-h">
                  <div className="card-header">
                    <h2 id="health-h">
                      <Activity size={16} aria-hidden /> Source freshness
                    </h2>
                    <Link to="/admin/connectors" className="small">
                      Details
                    </Link>
                  </div>
                  <p style={{ margin: 0 }}>
                    <strong>{d.health.healthy}</strong> of {d.health.connectors} connectors healthy.
                  </p>
                  {d.health.stale_or_failing.length ? (
                    <ul className="small" style={{ paddingLeft: 18 }}>
                      {d.health.stale_or_failing.map((c) => (
                        <li key={c.key}>
                          {c.display_name}: <span className="badge badge-warning">{c.state.replace(/_/g, ' ')}</span>
                          {c.hours_since_success !== null ? ` - ${c.hours_since_success.toFixed(0)} h since success` : ''}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="small muted">All enabled sources are within their freshness targets.</p>
                  )}
                </section>

                <section className="card" aria-labelledby="wl-h">
                  <div className="card-header">
                    <h2 id="wl-h">
                      <Star size={16} aria-hidden /> Watchlists
                    </h2>
                    <Link to="/watchlists" className="small">
                      Manage
                    </Link>
                  </div>
                  {d.watchlists.length === 0 ? (
                    <EmptyState title="No watchlists yet" />
                  ) : (
                    <ul className="list-plain">
                      {d.watchlists.map((w) => (
                        <li key={w.id} className="row-between">
                          <Link to={`/watchlists/${w.id}`}>{w.name}</Link>
                          <span className="badge badge-neutral">{w.visibility}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>
            </div>
          </div>
        )}
      </QueryView>
    </>
  );
}
