import { useEffect, useId, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Bell,
  BookOpen,
  CalendarDays,
  ChevronDown,
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
} from 'lucide-react';
import { api } from '../api/endpoints';
import { PERMS, useAuth } from '../auth/context';
import { useLandscape } from '../state/landscapeContext';
import { fmtRelative } from '../lib/format';

interface NavItem {
  to: string;
  label: string;
  icon: typeof Home;
  perm?: string;
  anyPerm?: string[];
}

const NAV: NavItem[] = [
  { to: '/', label: 'Home', icon: Home },
  { to: '/feed', label: 'Feed', icon: Rss, perm: PERMS.eventRead },
  { to: '/landscape', label: 'Landscape', icon: LayoutGrid },
  { to: '/calendar', label: 'Calendar', icon: CalendarDays },
  { to: '/compare', label: 'Compare', icon: Columns3 },
  { to: '/ask', label: 'Ask', icon: MessageSquareText, perm: PERMS.ask },
  { to: '/briefs', label: 'Briefs', icon: FileText },
  { to: '/alerts', label: 'Alerts', icon: Bell, perm: PERMS.eventRead },
  { to: '/watchlists', label: 'Watchlists', icon: Star },
  { to: '/review', label: 'Review', icon: ListChecks, perm: PERMS.entityCurate },
  { to: '/ai-transparency', label: 'AI transparency', icon: ShieldCheck },
  {
    to: '/admin',
    label: 'Admin',
    icon: Settings,
    anyPerm: [PERMS.userAdmin, PERMS.configAdmin, PERMS.sourceRead, PERMS.auditRead, PERMS.trainingCurate, PERMS.connectorAdmin],
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
      <label htmlFor={id} className="small strong hide-sm">
        Landscape
      </label>
      <select
        id={id}
        value={landscapeId ?? ''}
        onChange={(e) => setLandscapeId(e.target.value)}
        disabled={loading || landscapes.length === 0}
        style={{ maxWidth: 260 }}
        aria-label="Selected landscape"
      >
        {landscapes.length === 0 ? <option value="">{loading ? 'Loading...' : 'No landscapes'}</option> : null}
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
        aria-label={`Inbox, ${unread.length} unread`}
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
            <strong>Inbox</strong>
            <span className="small muted">{unread.length} unread</span>
          </div>
          {items.length === 0 ? <p className="small muted" style={{ padding: 8 }}>No notifications.</p> : null}
          <ul className="list-plain" style={{ maxHeight: 360, overflowY: 'auto' }}>
            {items.slice(0, 12).map((n) => {
              const evId = (n.payload.event_id as string | undefined) ?? n.intel_event_ids[0];
              const title = n.payload.title ?? n.kind;
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
                      <div className="tiny muted">{fmtRelative(n.created_at)}</div>
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
            Open full inbox
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
            <div className="small muted">Tenant: {me.tenant?.name ?? '-'}</div>
            <div className="row" style={{ marginTop: 6 }}>
              {me.roles.map((r) => (
                <span key={r} className="badge badge-neutral">
                  <ShieldCheck size={11} aria-hidden /> {r.replace(/_/g, ' ')}
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

function StaleBanner() {
  const { landscapeId } = useLandscape();
  const q = useQuery({ queryKey: ['dashboard', landscapeId ?? null], queryFn: () => api.dashboard(landscapeId), staleTime: 60_000 });
  const h = q.data?.health;
  if (!h?.banner) return null;
  return (
    <div className="banner banner-warning" role="status">
      <AlertTriangle size={18} aria-hidden />
      <div>
        <p>
          <strong>Stale data warning:</strong> {h.banner}
        </p>
        {h.stale_or_failing.length ? (
          <p className="small">
            Affected sources:{' '}
            {h.stale_or_failing.map((c) => `${c.display_name} (${c.state.replace(/_/g, ' ')})`).join(', ')}.
          </p>
        ) : null}
      </div>
    </div>
  );
}

export function Layout() {
  const { can } = useAuth();
  const [navOpen, setNavOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setNavOpen(false), [location.pathname]);
  const visible = NAV.filter((n) => (n.perm ? can(n.perm) : n.anyPerm ? n.anyPerm.some(can) : true));
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
            <small>Competitive &amp; Clinical Intelligence</small>
          </span>
        </Link>
        <ul className="nav">
          {visible.map((n) => {
            const Icon = n.icon;
            return (
              <li key={n.to}>
                <NavLink to={n.to} end={n.to === '/'} className={({ isActive }) => (isActive ? 'active' : undefined)}>
                  <Icon size={17} aria-hidden />
                  {n.label}
                </NavLink>
              </li>
            );
          })}
        </ul>
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
