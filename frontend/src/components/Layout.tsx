import { useEffect, useId, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Bell,
  BookOpen,
  CalendarDays,
  ChevronDown,
  Clock,
  Columns3,
  FileText,
  Home,
  Info,
  LayoutGrid,
  ListChecks,
  LogOut,
  Menu,
  MessageSquareText,
  Rss,
  Settings,
  ShieldCheck,
  Star,
  User as UserIcon,
  X,
} from 'lucide-react';
import { api } from '../api/endpoints';
import { PERMS, useAuth } from '../auth/context';
import { useLandscape } from '../state/landscapeContext';
import { fmtRelative } from '../lib/format';
import { humanizeEnum, notificationKindLabel, sourceLabel, sourceStateLabel } from '../lib/labels';

interface NavItem {
  to: string;
  label: string;
  description: string;
  icon: typeof Home;
  perm?: string;
  anyPerm?: string[];
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const NAV: NavSection[] = [
  {
    title: 'Overview',
    items: [
      { to: '/', label: 'Home', description: 'Top alerts for your drugs', icon: Home },
      { to: '/feed', label: 'All changes', description: 'Every detected competitor change', icon: Rss, perm: PERMS.eventRead },
      { to: '/calendar', label: 'Upcoming milestones', description: 'Expected readouts and key dates', icon: CalendarDays },
    ],
  },
  {
    title: 'Investigate',
    items: [
      { to: '/landscape', label: 'Competitor landscape', description: 'Who is developing what', icon: LayoutGrid },
      { to: '/compare', label: 'Compare drugs', description: 'Side-by-side drug profiles', icon: Columns3 },
      { to: '/ask', label: 'Ask a question', description: 'Answers that cite their sources', icon: MessageSquareText, perm: PERMS.ask },
    ],
  },
  {
    title: 'Share & stay informed',
    items: [
      { to: '/briefs', label: 'Executive briefs', description: 'Summaries to share with leadership', icon: FileText },
      { to: '/alerts', label: 'Alerts & inbox', description: 'Notifications and alert rules', icon: Bell, perm: PERMS.eventRead },
    ],
  },
  {
    title: 'Manage',
    items: [
      { to: '/watchlists', label: 'Watchlists', description: 'What you track', icon: Star },
      { to: '/review', label: 'Data review queue', description: 'Confirm names matched in sources', icon: ListChecks, perm: PERMS.entityCurate },
      { to: '/ai-transparency', label: 'How the AI works', description: 'Methods, limits and oversight', icon: ShieldCheck },
      {
        to: '/admin',
        label: 'Settings & data sources',
        description: 'Sources, users and rules',
        icon: Settings,
        anyPerm: [PERMS.userAdmin, PERMS.configAdmin, PERMS.sourceRead, PERMS.auditRead, PERMS.trainingCurate, PERMS.connectorAdmin],
      },
    ],
  },
];

function useClickOutside(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, close]);
  return ref;
}

function LandscapeSelect() {
  const { landscapes, landscapeId, setLandscapeId, loading } = useLandscape();
  const id = useId();
  return (
    <div className="row" style={{ flexWrap: 'nowrap' }}>
      <label htmlFor={id} className="small strong hide-sm" title="A landscape is the market you are monitoring: your drug(s) plus the competitors, trials and companies around them.">
        Market:
      </label>
      <select
        id={id}
        value={landscapeId ?? ''}
        onChange={(e) => setLandscapeId(e.target.value)}
        disabled={loading || landscapes.length === 0}
        style={{ maxWidth: 260 }}
        aria-label="Market (landscape) you are viewing"
      >
        {landscapes.length === 0 ? <option value="">{loading ? 'Loading...' : 'No landscapes yet'}</option> : null}
        {landscapes.map((l) => (
          <option key={l.id} value={l.id}>
            {l.name}
          </option>
        ))}
      </select>
    </div>
  );
}

function InboxBell() {
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useClickOutside(open, () => setOpen(false));
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['inbox'], queryFn: () => api.inbox(false), refetchInterval: 60_000, enabled: can(PERMS.eventRead) });
  const markRead = useMutation({ mutationFn: api.markRead, onSuccess: () => qc.invalidateQueries({ queryKey: ['inbox'] }) });
  const items = q.data ?? [];
  const unread = items.filter((n) => n.status !== 'read');
  if (!can(PERMS.eventRead)) return null;
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        type="button"
        className="btn btn-ghost btn-icon"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={`Notifications, ${unread.length} unread`}
        title="Notifications"
        onClick={() => setOpen((o) => !o)}
        style={{ position: 'relative' }}
      >
        <Bell size={18} aria-hidden />
        {unread.length > 0 ? (
          <span className="bell-count" aria-hidden>
            {unread.length > 99 ? '99+' : unread.length}
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="menu" style={{ width: 360 }}>
          <div className="row-between" style={{ padding: '4px 8px 8px' }}>
            <strong>Notifications</strong>
            <span className="small muted">{unread.length} unread</span>
          </div>
          {items.length === 0 ? (
            <p className="small muted" style={{ padding: 8 }}>
              No notifications yet. Alerts you subscribe to (and changes escalated to you) will appear here.
            </p>
          ) : null}
          <ul className="list-plain" style={{ maxHeight: 360, overflowY: 'auto' }}>
            {items.slice(0, 12).map((n) => {
              const evId = (n.payload.event_id as string | undefined) ?? n.intel_event_ids[0];
              const title = n.payload.title ?? notificationKindLabel(n.kind);
              return (
                <li key={n.id} style={{ padding: '6px 8px' }}>
                  <div className="row-between" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
                    <div style={{ minWidth: 0 }}>
                      {n.status !== 'read' ? <span className="badge badge-info">Unread</span> : null}{' '}
                      {evId ? (
                        <Link
                          to={`/events/${evId}`}
                          onClick={() => {
                            setOpen(false);
                            if (n.status !== 'read') markRead.mutate(n.id);
                          }}
                        >
                          {title}
                        </Link>
                      ) : (
                        <span>{title}</span>
                      )}
                      <div className="tiny muted">
                        {notificationKindLabel(n.kind)} - {fmtRelative(n.created_at)}
                      </div>
                    </div>
                    {n.status !== 'read' ? (
                      <button type="button" className="btn btn-sm btn-ghost" onClick={() => markRead.mutate(n.id)}>
                        Mark read
                      </button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
          <Link className="menu-item" to="/alerts?tab=inbox" onClick={() => setOpen(false)}>
            Open inbox and alert settings
          </Link>
        </div>
      ) : null}
    </div>
  );
}

function UserMenu() {
  const { me, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useClickOutside(open, () => setOpen(false));
  if (!me) return null;
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button type="button" className="btn btn-ghost" aria-haspopup="true" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <UserIcon size={16} aria-hidden />
        <span className="hide-sm">{me.user.display_name ?? me.user.email}</span>
        <ChevronDown size={14} aria-hidden />
      </button>
      {open ? (
        <div className="menu">
          <div style={{ padding: '6px 10px' }}>
            <div className="strong">{me.user.display_name}</div>
            <div className="small muted">{me.user.email}</div>
            <div className="small muted">Organisation: {me.tenant?.name ?? '-'}</div>
            <div className="row" style={{ marginTop: 6 }}>
              {me.roles.map((r) => (
                <span key={r} className="badge badge-neutral">
                  <ShieldCheck size={11} aria-hidden /> {humanizeEnum(r)}
                </span>
              ))}
            </div>
          </div>
          <hr className="divider" style={{ margin: '6px 0' }} />
          <button type="button" className="menu-item" onClick={logout}>
            <LogOut size={15} aria-hidden /> Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}

const STALE_DISMISS_KEY = 'xdata.staleNotice.dismissed';

function readDismissed(): string | null {
  try {
    return window.sessionStorage.getItem(STALE_DISMISS_KEY);
  } catch {
    return null;
  }
}

function StaleBanner() {
  const { landscapeId } = useLandscape();
  const q = useQuery({ queryKey: ['dashboard', landscapeId ?? null], queryFn: () => api.dashboard(landscapeId), staleTime: 60_000 });
  const h = q.data?.health;
  // Dismissal is remembered for this browser tab only, and only for the same set of affected sources.
  const signature = h ? h.stale_or_failing.map((c) => `${c.key}:${c.state}`).join(',') : '';
  const [dismissed, setDismissed] = useState<string | null>(() => readDismissed());
  if (!h?.banner || dismissed === signature) return null;
  const dismiss = () => {
    setDismissed(signature);
    try {
      window.sessionStorage.setItem(STALE_DISMISS_KEY, signature);
    } catch {
      /* storage unavailable: dismiss for this render only */
    }
  };
  const affected = h.stale_or_failing.map((c) => `${sourceLabel(c.key) !== humanizeEnum(c.key) ? sourceLabel(c.key) : c.display_name} (${sourceStateLabel(c.state)})`);
  return (
    <div className="banner banner-notice" role="status">
      <Clock size={17} aria-hidden />
      <p style={{ flex: 1 }}>
        {affected.length ? (
          <>
            Some data sources haven&rsquo;t been updated recently, so recent changes from them may be missing: {affected.join(', ')}.{' '}
          </>
        ) : (
          <>Some data sources haven&rsquo;t been updated recently, so recent changes may be missing. </>
        )}
        <Link to="/admin/connectors">See data sources</Link>
      </p>
      <button type="button" className="btn btn-ghost btn-icon btn-sm" onClick={dismiss} aria-label="Dismiss this notice for this session" title="Dismiss for this session">
        <X size={15} aria-hidden />
      </button>
    </div>
  );
}

export function Layout() {
  const { can } = useAuth();
  const [navOpen, setNavOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setNavOpen(false), [location.pathname]);
  const allowed = (n: NavItem) => (n.perm ? can(n.perm) : n.anyPerm ? n.anyPerm.some(can) : true);
  const sections = NAV.map((sec) => ({ ...sec, items: sec.items.filter(allowed) })).filter((sec) => sec.items.length > 0);
  return (
    <div className="shell">
      <a href="#main" className="skip-link">
        Skip to main content
      </a>
      <nav className={`sidebar ${navOpen ? 'open' : ''}`} aria-label="Primary">
        <Link to="/" className="brand">
          <BookOpen size={22} aria-hidden />
          <span>
            XData CI Agent
            <small>Competitor &amp; clinical intelligence</small>
          </span>
        </Link>
        <div className="nav">
          {sections.map((sec) => (
            <div key={sec.title} className="nav-section">
              <div className="nav-section-title" id={`nav-${sec.title.replace(/\W+/g, '-').toLowerCase()}`}>
                {sec.title}
              </div>
              <ul aria-labelledby={`nav-${sec.title.replace(/\W+/g, '-').toLowerCase()}`}>
                {sec.items.map((n) => {
                  const Icon = n.icon;
                  const descId = `nav-desc-${n.to.replace(/\W+/g, '') || 'home'}`;
                  return (
                    <li key={n.to}>
                      <NavLink
                        to={n.to}
                        end={n.to === '/'}
                        aria-label={n.label}
                        aria-describedby={descId}
                        className={({ isActive }) => (isActive ? 'active' : undefined)}
                      >
                        <Icon size={17} aria-hidden className="nav-icon" />
                        <span className="nav-text">
                          <span className="nav-label">{n.label}</span>
                          <span className="nav-desc" id={descId}>
                            {n.description}
                          </span>
                        </span>
                      </NavLink>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      </nav>
      <header className="topbar">
        <button
          type="button"
          className="btn btn-ghost btn-icon menu-toggle"
          aria-label={navOpen ? 'Close navigation' : 'Open navigation'}
          aria-expanded={navOpen}
          onClick={() => setNavOpen((o) => !o)}
        >
          <Menu size={18} aria-hidden />
        </button>
        <LandscapeSelect />
        <span className="spacer" />
        <InboxBell />
        <UserMenu />
      </header>
      <main id="main" className="main" tabIndex={-1}>
        <StaleBanner />
        <Outlet />
      </main>
      <footer className="footer">
        <Info size={14} aria-hidden />
        <span>Decision-support output. Facts are evidence-linked; interpretations are AI-generated hypotheses.</span>
      </footer>
    </div>
  );
}
