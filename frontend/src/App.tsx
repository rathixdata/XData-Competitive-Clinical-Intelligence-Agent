import { useEffect } from 'react';
import { Route, Routes, useLocation } from 'react-router-dom';
import { AuthProvider } from './auth/AuthProvider';
import { RequireAuth } from './auth/RequireAuth';
import { RequirePerm } from './auth/RequirePerm';
import { PERMS } from './auth/context';
import { Layout } from './components/Layout';
import { ToastProvider } from './components/Toasts';
import { LandscapeProvider } from './state/LandscapeProvider';
import { AdminPage } from './pages/admin/AdminPage';
import { AlertsPage } from './pages/AlertsPage';
import { AskPage } from './pages/AskPage';
import { AssetDetailPage } from './pages/AssetDetailPage';
import { BriefDetailPage, BriefsListPage } from './pages/BriefsPage';
import { CalendarPage } from './pages/CalendarPage';
import { ComparePage } from './pages/ComparePage';
import { EntityReviewPage } from './pages/EntityReviewPage';
import { EventDetailPage } from './pages/event/EventDetailPage';
import { FeedPage } from './pages/FeedPage';
import { HomePage } from './pages/HomePage';
import { TransparencyPage } from './pages/TransparencyPage';
import { LandscapePage } from './pages/LandscapePage';
import { LoginPage } from './pages/LoginPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { WatchlistDetailPage, WatchlistsPage } from './pages/WatchlistsPage';

const TITLES: [RegExp, string][] = [
  [/^\/$/, 'Portfolio'],
  [/^\/feed/, 'Intelligence feed'],
  [/^\/events\//, 'Event detail'],
  [/^\/landscape/, 'Landscape'],
  [/^\/assets\//, 'Asset'],
  [/^\/compare/, 'Compare assets'],
  [/^\/calendar/, 'Catalyst calendar'],
  [/^\/ask/, 'Ask the landscape'],
  [/^\/briefs/, 'Executive briefs'],
  [/^\/alerts/, 'Alerts'],
  [/^\/watchlists/, 'Watchlists'],
  [/^\/review/, 'Entity review'],
  [/^\/admin/, 'Administration'],
  [/^\/login/, 'Sign in'],
];

/** Per-route document title + focus management so screen-reader users hear navigation. */
function RouteAnnouncer() {
  const { pathname } = useLocation();
  useEffect(() => {
    const t = TITLES.find(([re]) => re.test(pathname))?.[1] ?? 'XData';
    document.title = `${t} - XData CI Agent`;
    const main = document.getElementById('main');
    if (main && document.activeElement && document.activeElement !== document.body) main.focus({ preventScroll: true });
  }, [pathname]);
  return null;
}

export function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <RouteAnnouncer />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <RequireAuth>
                <LandscapeProvider>
                  <Layout />
                </LandscapeProvider>
              </RequireAuth>
            }
          >
            <Route index element={<HomePage />} />
            <Route
              path="feed"
              element={
                <RequirePerm perm={PERMS.eventRead}>
                  <FeedPage />
                </RequirePerm>
              }
            />
            <Route path="events/:id" element={<EventDetailPage />} />
            <Route path="landscape" element={<LandscapePage />} />
            <Route path="assets/:id" element={<AssetDetailPage />} />
            <Route path="compare" element={<ComparePage />} />
            <Route path="calendar" element={<CalendarPage />} />
            {/* one route (optional segment) so the page stays mounted when a new session id is assigned */}
            <Route
              path="ask/:sessionId?"
              element={
                <RequirePerm perm={PERMS.ask}>
                  <AskPage />
                </RequirePerm>
              }
            />
            <Route path="briefs" element={<BriefsListPage />} />
            <Route path="briefs/:id" element={<BriefDetailPage />} />
            <Route path="alerts" element={<AlertsPage />} />
            <Route path="watchlists" element={<WatchlistsPage />} />
            <Route path="watchlists/:id" element={<WatchlistDetailPage />} />
            <Route path="review" element={<EntityReviewPage />} />
            <Route path="admin/:tab?" element={<AdminPage />} />
            <Route path="ai-transparency" element={<TransparencyPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </AuthProvider>
    </ToastProvider>
  );
}
