import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, buildQuery, request, setUnauthorizedHandler, toApiError } from './client';
import { tokenStore } from '../auth/tokenStore';
import { jsonResponse } from '../test/utils';

afterEach(() => {
  vi.unstubAllGlobals();
  setUnauthorizedHandler(null);
  tokenStore.clear();
});

describe('buildQuery', () => {
  it('repeats array params and drops empty values', () => {
    expect(buildQuery({ band: ['Feed', 'High Priority'], q: '', min_score: 50, x: undefined, y: null })).toBe(
      '?band=Feed&band=High+Priority&min_score=50',
    );
    expect(buildQuery({})).toBe('');
  });
});

describe('toApiError', () => {
  it('reads the backend error envelope', async () => {
    const err = await toApiError(jsonResponse({ error: { code: 'not_found', message: 'event not found', details: {} } }, 404));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.code).toBe('not_found');
    expect(err.message).toBe('event not found');
  });

  it('summarises request-validation details', async () => {
    const err = await toApiError(
      jsonResponse(
        { error: { code: 'validation_failed', message: 'invalid request', details: [{ loc: ['body', 'reason'], msg: 'Field required', type: 'missing' }] } },
        422,
      ),
    );
    expect(err.message).toBe('Invalid request - reason: Field required');
  });

  it('falls back to FastAPI {detail} bodies and non-JSON bodies', async () => {
    expect((await toApiError(jsonResponse({ detail: 'Not Found' }, 404))).message).toBe('Not Found');
    const plain = await toApiError(new Response('upstream exploded', { status: 502, statusText: 'Bad Gateway' }));
    expect(plain.status).toBe(502);
    expect(plain.message).toBe('Bad Gateway');
  });
});

describe('request', () => {
  it('sends the bearer token and parses JSON', async () => {
    tokenStore.set('tok-123', 3600);
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(request('/events', { query: { band: ['Feed'] } })).resolves.toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/events?band=Feed');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok-123');
  });

  it('returns undefined for 204', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(request('/saved-views/x', { method: 'DELETE' })).resolves.toBeUndefined();
  });

  it('on 401 clears the token, calls the unauthorized handler and throws the server message', async () => {
    tokenStore.set('expired', 3600);
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ error: { code: 'unauthorized', message: 'token expired' } }, 401)));
    const err = await request('/auth/me').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).isUnauthorized).toBe(true);
    expect((err as ApiError).message).toBe('token expired');
    expect(handler).toHaveBeenCalledTimes(1);
    expect(tokenStore.get()).toBeNull();
    expect(window.sessionStorage.getItem('xdata.auth')).toBeNull();
  });

  it('does not redirect for anonymous calls (failed login)', async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ error: { code: 'unauthorized', message: 'invalid credentials' } }, 401)));
    await expect(request('/auth/login', { method: 'POST', body: {}, anonymous: true })).rejects.toThrow('invalid credentials');
    expect(handler).not.toHaveBeenCalled();
  });

  it('maps network failures to a readable ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const err = (await request('/dashboard').catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(0);
    expect(err.code).toBe('network_error');
    expect(err.message).toMatch(/could not be reached/);
  });
});

describe('tokenStore', () => {
  it('stores in sessionStorage (never localStorage) and expires', () => {
    vi.useFakeTimers();
    tokenStore.set('abc', 120);
    expect(window.sessionStorage.getItem('xdata.auth')).toContain('abc');
    expect(window.localStorage.length).toBe(0);
    expect(tokenStore.get()).toBe('abc');
    vi.advanceTimersByTime(121_000);
    expect(tokenStore.get()).toBeNull();
    vi.useRealTimers();
  });
});
