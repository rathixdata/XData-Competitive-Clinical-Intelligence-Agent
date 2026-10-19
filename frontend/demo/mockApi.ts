/**
 * Static demo backend: replays API responses recorded from a real run of the pipeline (demo/record.spec.ts),
 * so the UI can be hosted as a single file with no server. Only built when VITE_DEMO=1.
 */
import fixtures from './fixtures.json';

type Rec = { method: string; path: string; query: string; body: string; status: number; contentType: string; text: string };

const RECS = fixtures as Rec[];
const API = '/api/v1';

function envelope(status: number, code: string, message: string): Response {
  return new Response(JSON.stringify({ error: { code, message } }), { status, headers: { 'Content-Type': 'application/json' } });
}

function reply(r: Rec): Response {
  if (r.status === 204) return new Response(null, { status: 204 });
  return new Response(r.text, { status: r.status, headers: { 'Content-Type': r.contentType || 'application/json' } });
}

const QUESTIONS = RECS.filter((r) => r.method === 'POST' && r.path === '/ask').map((r) => {
  try {
    return String((JSON.parse(r.body) as { question?: string }).question ?? '');
  } catch {
    return '';
  }
}).filter(Boolean);

const norm = (q: string) => q.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

function question(body: string): string {
  try {
    return norm(String((JSON.parse(body) as { question?: string }).question ?? ''));
  } catch {
    return '';
  }
}

function assetSet(body: string): string {
  try {
    return [...((JSON.parse(body) as { asset_ids?: string[] }).asset_ids ?? [])].sort().join(',');
  } catch {
    return '';
  }
}

function match(method: string, path: string, query: string, body: string): Rec | undefined {
  const same = RECS.filter((r) => r.method === method && r.path === path);
  if (method === 'POST' && (path === '/auth/login' || path === '/reports/briefs')) return same[0];
  if (method === 'POST' && path === '/ask') return same.find((r) => question(r.body) === question(body));
  if (method === 'POST' && path === '/comparisons') return same.find((r) => assetSet(r.body) === assetSet(body));
  const exact = same.find((r) => r.query === query && r.body === body) ?? same.find((r) => r.query === query);
  if (exact) return exact;
  // Same path, different filters: serve the closest recorded variant (most shared query params).
  const want = new Set(query.split('&').filter(Boolean));
  return same
    .map((r) => ({ r, score: r.query.split('&').filter((p) => want.has(p)).length - Math.abs(r.query.split('&').length - want.size) * 0.1 }))
    .sort((a, b) => b.score - a.score)[0]?.r;
}

function banner(): void {
  const el = document.createElement('div');
  el.setAttribute('role', 'note');
  el.textContent = 'Hosted demo: recorded output of the real pipeline, read-only. Ask answers the suggested questions; Compare: XD-101 vs one competitor.';
  el.style.cssText = 'position:fixed;bottom:0;left:0;right:0;z-index:9999;padding:6px 12px;font:12px/1.4 system-ui,sans-serif;text-align:center;background:#1e293b;color:#f8fafc';
  document.body.appendChild(el);
  document.body.style.paddingBottom = '28px';
}

export function installDemoApi(): void {
  banner();
  const real = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, window.location.href);
    const at = url.pathname.indexOf(API);
    if (at === -1) return real(input, init);
    const path = url.pathname.slice(at + API.length);
    const method = (init?.method ?? 'GET').toUpperCase();
    const query = [...url.searchParams.entries()].sort().map(([k, v]) => `${k}=${v}`).join('&');
    const body = typeof init?.body === 'string' ? init.body : '';
    await new Promise((r) => setTimeout(r, path.startsWith('/ask') ? 600 : 80));
    // No streaming in the demo: a 404 makes the client fall back to the plain POST /ask.
    if (path === '/ask/stream') return envelope(404, 'demo_no_stream', 'not available in the demo');
    const r = match(method, path, query, body);
    if (r) return reply(r);
    if (path === '/ask') {
      return envelope(422, 'demo_question', `This hosted demo replays recorded answers. Try one of: ${QUESTIONS.join(' · ')}. Run the full app to ask anything.`);
    }
    if (path === '/comparisons') {
      return envelope(422, 'demo_comparison', 'This combination was not recorded in the hosted demo. Compare XD-101 with any one competitor.');
    }
    if (method !== 'GET') return envelope(403, 'demo_read_only', 'This hosted demo is read-only. Changes are disabled here; run the full app to try them.');
    return envelope(404, 'demo_not_recorded', 'This view was not captured in the hosted demo.');
  };
}
