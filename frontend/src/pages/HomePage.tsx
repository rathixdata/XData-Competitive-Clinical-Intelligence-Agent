import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Activity, ArrowRight, CalendarDays, Lightbulb, Star, X } from 'lucide-react';
import { api } from '../api/endpoints';
import { BANDS } from '../api/types';
import { BandBadge, BandLegend, BasisBadge, ChangedDateBadge, ReviewBadge, StatusBadge } from '../components/Badges';
import { EmptyState, QueryView } from '../components/States';
import { AddDrugButton } from '../components/LandscapeSetup';
import { useLandscape } from '../state/landscapeContext';
import { fmtRelative } from '../lib/format';
import { eventTypeLabel, sourceLabel, sourceStateLabel, visibilityLabel } from '../lib/labels';
import { catalystDate, previousDate } from '../lib/catalyst';

const GUIDE_KEY = 'xdata.home.guideDismissed';

function readGuideDismissed(): boolean {
  try {
    return window.localStorage.getItem(GUIDE_KEY) === '1';
  } catch {
    return false;
  }
}

/** Dismissible "how to use this" card for first-time users. */
function GettingStarted() {
  const [hidden, setHidden] = useState(readGuideDismissed);
  if (hidden) return null;
  const dismiss = () => {
    setHidden(true);
    try {
      window.localStorage.setItem(GUIDE_KEY, '1');
    } catch {
      /* storage unavailable: hide for this visit only */
    }
  };
  return (
    <section className="card guide" aria-labelledby="guide-h">
      <div className="card-header">
        <h2 id="guide-h">
          <Lightbulb size={16} aria-hidden /> How to use this
        </h2>
        <button type="button" className="btn btn-ghost btn-sm" onClick={dismiss} aria-label="Hide the how-to-use guide" title="Hide this guide (you can find each step in the menu)">
          <X size={14} aria-hidden /> Hide
        </button>
      </div>
      <ol className="guide-steps">
        <li>
          <strong>Check the top alerts.</strong> &ldquo;Material developments&rdquo; below lists the competitor changes that matter most to your drugs, highest priority first.
        </li>
        <li>
          <strong>Open an alert</strong> to see what changed, why it matters to your drug, and the source evidence behind every fact.
        </li>
        <li>
          <strong>
            <Link to="/ask">Ask a question</Link>
          </strong>{' '}
          in plain English, e.g. &ldquo;What changed this week?&rdquo; Answers cite their sources.
        </li>
        <li>
          <strong>
            <Link to="/briefs">Share an executive brief</Link>
          </strong>{' '}
          with leadership: a one-page summary of the period, reviewed by an analyst.
        </li>
      </ol>
    </section>
  );
}

export function HomePage() {
  const { landscapeId, landscape } = useLandscape();
  const q = useQuery({ queryKey: ['dashboard', landscapeId ?? null], queryFn: () => api.dashboard(landscapeId), staleTime: 60_000 });

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Portfolio</h1>
          <p>
            What competitors changed recently{landscape ? ` in ${landscape.name}` : ''}, and how much it matters to your drugs. Start with the highest-priority items, then open one to see the
            evidence.
          </p>
        </div>
        <Link to="/feed" className="btn btn-primary">
          See all changes <ArrowRight size={15} aria-hidden />
        </Link>
      </div>
      <QueryView query={q} loadingLabel="Loading portfolio">
        {(d) => (
          <div className="stack" style={{ gap: 16 }}>
            <GettingStarted />
            <section className="card" aria-labelledby="bands-h">
              <div className="card-header">
                <div>
                  <h2 id="bands-h">Changes by priority (last 30 days)</h2>
                  <p className="small muted" style={{ margin: 0 }}>
                    Every detected change gets an importance score from 0 to 100 and a priority level. Click a level to see those changes.
                  </p>
                </div>
              </div>
              <ul className="row list-plain band-counts">
                {BANDS.slice()
                  .reverse()
                  .map((b) => (
                    <li key={b} style={{ padding: 0, border: 0 }}>
                      <Link to={`/feed?band=${encodeURIComponent(b)}`} className="band-count" aria-label={`${d.band_counts_30d[b] ?? 0} ${b} changes - show them`}>
                        <span className="band-count-num">{d.band_counts_30d[b] ?? 0}</span>
                        <BandBadge band={b} />
                      </Link>
                    </li>
                  ))}
              </ul>
              <BandLegend />
            </section>

            <section aria-labelledby="assets-h">
              <div className="row-between">
                <h2 id="assets-h">Your assets</h2>
                <AddDrugButton landscapeId={landscapeId} className="btn btn-sm" />
              </div>
              <p className="small muted section-intro">Your own drugs in this market, with how many competitor changes affected each one.</p>
              {d.assets.length === 0 ? (
                <div className="card">
                  <EmptyState title="None of your own drugs are in this market yet">
                    Click &ldquo;Add your drug&rdquo; and describe it (target, disease, line of therapy). Competitor changes will then be scored against it.
                  </EmptyState>
                </div>
              ) : (
                <div className="grid grid-auto">
                  {d.assets.map((a) => (
                    <article key={a.asset_id} className="card stack-sm">
                      <div className="row-between">
                        <h3 style={{ margin: 0 }}>
                          <Link to={`/assets/${a.asset_id}`}>{a.name}</Link>
                        </h3>
                        {a.stage ? (
                          <span className="badge badge-neutral" title="Development stage">
                            {a.stage}
                          </span>
                        ) : null}
                      </div>
                      <p className="small muted" style={{ margin: 0 }}>
                        {[a.profile?.mechanism, a.profile?.population].filter(Boolean).map(String).join(' - ') || 'No profile details'}
                      </p>
                      <dl className="kv small">
                        <dt title="High priority or executive alert changes nobody has marked as reviewed yet">High-priority, not yet reviewed</dt>
                        <dd>
                          <strong>{a.open_high_priority}</strong>
                        </dd>
                        <dt>Changes affecting it (30 days)</dt>
                        <dd>{a.events_30d}</dd>
                      </dl>
                      <Link to={`/feed?impacted_asset_id=${a.asset_id}&sort=score`} className="small">
                        See changes affecting {a.name} <ArrowRight size={12} aria-hidden />
                      </Link>
                    </article>
                  ))}
                </div>
              )}
            </section>

            <div className="grid grid-main-side">
              <section className="card" aria-labelledby="dev-h">
                <div className="card-header">
                  <div>
                    <h2 id="dev-h">Material developments</h2>
                    <p className="small muted" style={{ margin: 0 }}>
                      The competitor changes most likely to matter to your drugs. Open one to see why and the evidence.
                    </p>
                  </div>
                  <Link to="/feed?min_score=50&sort=score" className="small">
                    View all important changes
                  </Link>
                </div>
                {d.material_developments.length === 0 ? (
                  <EmptyState title="No important changes in the last 30 days">
                    When a competitor changes something that scores 50 or more for your drugs (for example a trial endpoint or an FDA label), it will appear here.
                  </EmptyState>
                ) : (
                  <ul className="list-plain">
                    {d.material_developments.map((e) => (
                      <li key={e.id} className="stack-sm dev-item">
                        <div className="row">
                          <BandBadge band={e.band} score={e.materiality_score} />
                          <span className="badge badge-neutral">{eventTypeLabel(e.primary_type)}</span>
                          <StatusBadge status={e.status} />
                          <ReviewBadge status={e.review_status} />
                        </div>
                        <Link to={`/events/${e.id}`} className="strong dev-title">
                          {e.title}
                        </Link>
                        <div className="small muted">
                          Found {fmtRelative(e.detected_at)}
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
                      <CalendarDays size={16} aria-hidden /> Upcoming milestones (next 90 days)
                    </h2>
                    <Link to="/calendar" className="small">
                      Open calendar
                    </Link>
                  </div>
                  <p className="small muted section-intro">Expected trial readouts, completions and regulatory dates for drugs in this market.</p>
                  {d.upcoming_catalysts.length === 0 ? (
                    <EmptyState title="No milestones expected in the next 90 days">Dates appear here as soon as a trial registry, company or regulator reports them.</EmptyState>
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
                      <Activity size={16} aria-hidden /> Data sources
                    </h2>
                    <Link to="/admin/connectors" className="small">
                      Details
                    </Link>
                  </div>
                  <p style={{ margin: 0 }}>
                    <strong>{d.health.healthy}</strong> of {d.health.connectors} data sources are up to date.
                  </p>
                  {d.health.stale_or_failing.length ? (
                    <ul className="small" style={{ paddingLeft: 18 }}>
                      {d.health.stale_or_failing.map((c) => (
                        <li key={c.key}>
                          <strong>{sourceLabel(c.key)}</strong>: <span className="muted">{sourceStateLabel(c.state)}</span>
                          {c.hours_since_success !== null ? ` - last updated ${c.hours_since_success.toFixed(0)} h ago` : ''}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="small muted">All sources were checked recently, so nothing should be missing.</p>
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
                  <p className="small muted section-intro">Companies, drugs and trials you follow closely.</p>
                  {d.watchlists.length === 0 ? (
                    <EmptyState title="No watchlists yet">Create one under Watchlists to follow specific competitors; their changes get boosted in your feed.</EmptyState>
                  ) : (
                    <ul className="list-plain">
                      {d.watchlists.map((w) => (
                        <li key={w.id} className="row-between">
                          <Link to={`/watchlists/${w.id}`}>{w.name}</Link>
                          <span className="badge badge-neutral" title="Who can see this watchlist">
                            {visibilityLabel(w.visibility)}
                          </span>
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
