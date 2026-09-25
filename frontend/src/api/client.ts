import { tokenStore } from '../auth/tokenStore';

export const API_BASE: string = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api/v1';

/** Error raised for every non-2xx response (or network failure). `message` is user-presentable. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }
}

type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

/** Registered once by the auth layer: invoked on any 401 so the app can route to the login page. */
export function setUnauthorizedHandler(fn: UnauthorizedHandler | null): void {
  unauthorizedHandler = fn;
}

export type QueryValue = string | number | boolean | null | undefined | (string | number | boolean)[];
export type Query = Record<string, QueryValue>;

export function buildQuery(query?: Query): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === '') continue;
    if (Array.isArray(v)) v.forEach((x) => params.append(k, String(x)));
    else params.append(k, String(v));
  }
  const s = params.toString();
  return s ? `?${s}` : '';
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  query?: Query;
  /** JSON body (serialised) */
  body?: unknown;
  /** Raw body (e.g. CSV) sent as-is */
  rawBody?: BodyInit;
  contentType?: string;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Skip the Authorization header (login). */
  anonymous?: boolean;
}

function readValidationDetails(details: unknown): string | null {
  if (!Array.isArray(details) || details.length === 0) return null;
  const parts = details
    .map((d) => {
      if (d && typeof d === 'object' && 'msg' in d) {
        const loc = Array.isArray((d as { loc?: unknown[] }).loc)
          ? ((d as { loc: unknown[] }).loc.filter((x) => x !== 'body').join('.') as string)
          : '';
        return loc ? `${loc}: ${String((d as { msg: unknown }).msg)}` : String((d as { msg: unknown }).msg);
      }
      return null;
    })
    .filter(Boolean);
  return parts.length ? parts.join('; ') : null;
}

/** Parse the backend's `{"error": {code, message, details}}` envelope (or FastAPI's `{"detail"}`). */
export async function toApiError(res: Response): Promise<ApiError> {
  let code = `http_${res.status}`;
  let message = res.statusText || `Request failed (${res.status})`;
  let details: unknown;
  try {
    const text = await res.text();
    if (text) {
      const data = JSON.parse(text) as unknown;
      if (data && typeof data === 'object') {
        const env = (data as { error?: { code?: string; message?: string; details?: unknown } }).error;
        if (env && typeof env === 'object') {
          code = env.code ?? code;
          message = env.message ?? message;
          details = env.details;
          const v = code === 'validation_failed' && message === 'invalid request' ? readValidationDetails(details) : null;
          if (v) message = `Invalid request - ${v}`;
        } else if ('detail' in data) {
          const d = (data as { detail: unknown }).detail;
          message = typeof d === 'string' ? d : (readValidationDetails(d) ?? message);
          details = d;
        }
      }
    }
  } catch {
    /* non-JSON body: keep status text */
  }
  if (res.status === 401 && !message) message = 'Your session has expired. Please sign in again.';
  return new ApiError(res.status, code, message, details);
}

function authHeaders(anonymous?: boolean): Record<string, string> {
  if (anonymous) return {};
  const t = tokenStore.get();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export async function rawRequest(path: string, opts: RequestOptions = {}): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json', ...authHeaders(opts.anonymous), ...opts.headers };
  let body: BodyInit | undefined;
  if (opts.rawBody !== undefined) {
    body = opts.rawBody;
    headers['Content-Type'] = opts.contentType ?? 'text/plain';
  } else if (opts.body !== undefined) {
    body = JSON.stringify(opts.body);
    headers['Content-Type'] = 'application/json';
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}${buildQuery(opts.query)}`, {
      method: opts.method ?? 'GET',
      headers,
      body,
      signal: opts.signal,
      credentials: 'same-origin',
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(0, 'network_error', 'Network error - the API could not be reached. Check your connection and retry.');
  }
  if (!res.ok) {
    const err = await toApiError(res);
    if (res.status === 401 && !opts.anonymous) {
      tokenStore.clear();
      unauthorizedHandler?.();
    }
    throw err;
  }
  return res;
}

/** JSON request. Returns `undefined` for 204 responses. */
export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await rawRequest(path, opts);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

function filenameFrom(res: Response, fallback: string): string {
  const cd = res.headers.get('Content-Disposition') ?? '';
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  return m ? decodeURIComponent(m[1]) : fallback;
}

/** Fetch a binary/text export and hand it to the browser as a file download. */
export async function download(path: string, fallbackName: string, opts: RequestOptions = {}): Promise<string> {
  const res = await rawRequest(path, { ...opts, headers: { Accept: '*/*', ...opts.headers } });
  const blob = await res.blob();
  const name = filenameFrom(res, fallbackName);
  saveBlob(blob, name);
  return name;
}

export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
