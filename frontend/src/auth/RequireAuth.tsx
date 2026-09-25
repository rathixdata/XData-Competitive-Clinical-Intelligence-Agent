import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './context';
import { ErrorState, Loading } from '../components/States';

export function RequireAuth({ children }: { children: ReactNode }) {
  const { token, me, loading, error, logout } = useAuth();
  const location = useLocation();
  if (!token) {
    const next = location.pathname + location.search;
    return <Navigate to={next === '/' ? '/login' : `/login?next=${encodeURIComponent(next)}`} replace />;
  }
  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
        <Loading label="Signing you in" />
      </div>
    );
  }
  if (error || !me) {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
        <div className="card">
          <ErrorState error={error ?? new Error('Could not load your profile.')} />
          <div className="row" style={{ justifyContent: 'center' }}>
            <button type="button" className="btn" onClick={logout}>
              Back to sign in
            </button>
          </div>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
