import { createContext, useContext } from 'react';
import type { Me } from '../api/types';
import type { PasswordCredentials } from './authProvider';

export interface AuthState {
  token: string | null;
  me: Me | undefined;
  loading: boolean;
  error: unknown;
  can: (permission: string) => boolean;
  login: (creds: PasswordCredentials) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}

/** Permission strings from GET /auth/me (server enforces; UI only hides/disables). */
export const PERMS = {
  eventRead: 'event:read',
  eventTriage: 'event:triage',
  narrativeEdit: 'narrative:edit',
  feedbackWrite: 'feedback:write',
  configAdmin: 'config:admin',
  auditRead: 'audit:read',
  auditExport: 'audit:export',
  connectorAdmin: 'connector:admin',
  reportWrite: 'report:write',
  reportApprove: 'report:approve',
  entityCurate: 'entity:curate',
  trainingCurate: 'training:curate',
  userAdmin: 'user:admin',
  landscapeWrite: 'landscape:write',
  watchlistWrite: 'watchlist:write',
  alertWrite: 'alert:write',
  ask: 'ask:use',
  sourceRead: 'source:read',
} as const;
