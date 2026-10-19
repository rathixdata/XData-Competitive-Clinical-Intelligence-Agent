/**
 * Records real API responses while crawling every screen, for the static demo build (`npm run build:demo`).
 * Run against a live API + seeded demo tenant:  npx playwright test -c e2e/playwright.config.ts ../demo/record.spec.ts
 */
import { test, type Page } from '@playwright/test';
import { writeFileSync } from 'node:fs';

type Rec = { method: string; path: string; query: string; body: string; status: number; contentType: string; text: string };
const recs = new Map<string, Rec>();

function keyOf(method: string, path: string, query: string, body: string) {
  return `${method} ${path}?${query} ${body}`;
}

test.setTimeout(1_200_000);

const save = () => writeFileSync(new URL('./fixtures.json', import.meta.url), JSON.stringify([...recs.values()]));

test('record demo fixtures', async ({ page }) => {
  page.on('response', async (res) => {
    const u = new URL(res.url());
    if (!u.pathname.startsWith('/api/v1')) return;
    const req = res.request();
    const ct = res.headers()['content-type'] ?? '';
    if (!/json|event-stream|text\/plain/.test(ct) && res.status() !== 204) return;
    let text = '';
    try {
      text = res.status() === 204 ? '' : await res.text();
    } catch {
      return;
    }
    const params = [...u.searchParams.entries()].sort().map(([k, v]) => `${k}=${v}`).join('&');
    let body = req.postData() ?? '';
    if (u.pathname.endsWith('/auth/login')) body = '';
    const path = u.pathname.replace(/^\/api\/v1/, '');
    recs.set(keyOf(req.method(), path, params, body), { method: req.method(), path, query: params, body, status: res.status(), contentType: ct, text });
  });

  const visited = new Set<string>();
  const settle = async (p: Page) => {
    await p.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => undefined);
    await p.waitForTimeout(400);
  };
  const visit = async (path: string) => {
    if (visited.has(path)) return;
    visited.add(path);
    await page.goto(path);
    await settle(page);
    save();
    console.log(`${recs.size} responses after ${path}`);
  };
  const links = async (re: RegExp) => {
    const hrefs = await page.$$eval('a[href]', (as) => as.map((a) => a.getAttribute('href') ?? ''));
    return [...new Set(hrefs.filter((h) => re.test(h)))];
  };

  await page.goto('/login');
  await page.getByLabel('Tenant').fill('demo-oncology');
  await page.getByLabel('Email').fill('analyst@demo.example');
  await page.getByLabel('Password').fill('ChangeMe-Demo-2026!');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.getByRole('heading', { level: 1, name: 'Portfolio' }).waitFor();
  await settle(page);
  visited.add('/');

  const top = ['/feed', '/landscape', '/compare', '/calendar', '/ask', '/briefs', '/alerts', '/watchlists', '/review', '/ai-transparency', '/admin'];
  const detail: string[] = [];
  for (const p of top) {
    await visit(p);
    detail.push(...(await links(/^\/(events|assets|briefs|watchlists|admin)\/[^/]+$/)));
  }
  await visit('/');
  detail.push(...(await links(/^\/(events|assets)\/[^/]+$/)));
  for (const p of [...new Set(detail)]) await visit(p);
  // second hop (e.g. events linked from asset pages)
  for (const p of [...new Set(detail)].filter((d) => d.startsWith('/assets/'))) {
    await page.goto(p);
    await settle(page);
    for (const e of await links(/^\/events\/[^/]+$/)) await visit(e);
  }

  // Feed filters / tabs
  await page.goto('/feed');
  await settle(page);
  for (const tab of await page.getByRole('tab').all()) {
    await tab.click().catch(() => undefined);
    await settle(page);
  }

  // Compare: pick assets if a selector exists
  await page.goto('/compare');
  await settle(page);
  for (const cb of (await page.getByRole('checkbox').all()).slice(0, 3)) await cb.check().catch(() => undefined);
  for (const b of await page.getByRole('button', { name: /compare/i }).all()) await b.click().catch(() => undefined);
  await settle(page);

  // Ask: every suggested question
  const questions = [
    'What changed this week?',
    'Which competitor trials changed their primary endpoint?',
    'Compare CA-201 and BRV-310',
    'What catalysts are expected in the next 6 months?',
    'What changed in NCT99000001?',
    'How does this affect XD-101?',
    'Is CA-201 better than XD-101?',
    'What is the overall survival result for CA-201?',
  ];
  for (const q of questions) {
    await page.goto('/ask');
    await settle(page);
    const box = page.getByRole('textbox').first();
    await box.fill(q);
    await box.press('Enter');
    await page.waitForResponse((r) => r.url().includes('/ask'), { timeout: 60_000 }).catch(() => undefined);
    await page.waitForTimeout(2500);
    await settle(page);
  }
  await visit('/ask');
  for (const s of await links(/^\/ask\/[^/]+$/)) await visit(s);

  save();
  console.log(`recorded ${recs.size} responses over ${visited.size} pages`);
});
