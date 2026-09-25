/**
 * Token acquisition. This is the ONLY module that knows how a bearer token is obtained, so adding
 * SSO (OIDC authorization-code + PKCE via the backend) means adding a strategy here and nothing else.
 */
import { request } from '../api/client';
import type { TokenOut } from '../api/types';
import { tokenStore } from './tokenStore';

export interface PasswordCredentials {
  tenant: string;
  email: string;
  password: string;
}

export async function loginWithPassword(creds: PasswordCredentials): Promise<void> {
  const out = await request<TokenOut>('/auth/login', {
    method: 'POST',
    body: { tenant: creds.tenant.trim(), email: creds.email.trim(), password: creds.password },
    anonymous: true,
  });
  tokenStore.set(out.access_token, out.expires_in);
}

/** Placeholder for SSO: returns false while the tenant has no SSO configured client-side. */
export function ssoAvailable(): boolean {
  return Boolean(import.meta.env.VITE_SSO_LOGIN_URL);
}

export function beginSso(tenant: string): void {
  const url = import.meta.env.VITE_SSO_LOGIN_URL as string | undefined;
  if (!url) return;
  const target = new URL(url, window.location.origin);
  target.searchParams.set('tenant', tenant);
  target.searchParams.set('redirect_uri', `${window.location.origin}/login`);
  window.location.assign(target.toString());
}

export function logout(): void {
  tokenStore.clear();
}
