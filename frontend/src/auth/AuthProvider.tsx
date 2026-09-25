import { useCallback, useEffect, useMemo, useSyncExternalStore, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocation, useNavigate } from 'react-router-dom';
import { setUnauthorizedHandler } from '../api/client';
import { api } from '../api/endpoints';
import { loginWithPassword, logout as doLogout, type PasswordCredentials } from './authProvider';
import { AuthContext, type AuthState } from './context';
import { tokenStore } from './tokenStore';

export function AuthProvider({ children }: { children: ReactNode }) {
  const token = useSyncExternalStore(tokenStore.subscribe, tokenStore.get, tokenStore.get);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();

  const meQ = useQuery({ queryKey: ['me', token], queryFn: api.me, enabled: Boolean(token), staleTime: 5 * 60_000, retry: false });

  useEffect(() => {
    setUnauthorizedHandler(() => {
      qc.clear();
      const here = window.location.pathname + window.location.search;
      if (!window.location.pathname.startsWith('/login')) {
        navigate(`/login?expired=1&next=${encodeURIComponent(here)}`, { replace: true });
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [qc, navigate]);

  const login = useCallback(
    async (creds: PasswordCredentials) => {
      qc.clear();
      await loginWithPassword(creds);
    },
    [qc],
  );

  const logout = useCallback(() => {
    doLogout();
    qc.clear();
    navigate('/login', { replace: true, state: { from: location.pathname } });
  }, [qc, navigate, location.pathname]);

  const value = useMemo<AuthState>(() => {
    const perms = new Set(meQ.data?.permissions ?? []);
    return {
      token,
      me: meQ.data,
      loading: Boolean(token) && meQ.isLoading,
      error: meQ.error,
      can: (p: string) => perms.has(p),
      login,
      logout,
    };
  }, [token, meQ.data, meQ.isLoading, meQ.error, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
