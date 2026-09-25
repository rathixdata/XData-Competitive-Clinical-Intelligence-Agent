import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FeedPage } from './FeedPage';
import { jsonResponse, renderWithProviders } from '../test/utils';

const EVENT = {
  id: 'e1',
  title: 'Competitor A Phase 3 trial NCT99000001: enrollment 320 to 480',
  band: 'Executive Alert',
  materiality_score: 93.2,
  primary_type: 'ENDPOINT_CHANGED',
  source: 'ctgov',
  status: 'published',
  review_status: 'Machine',
  detected_at: '2026-09-25T03:53:57Z',
  impacted_assets: [{ asset_id: 'x', asset_name: 'XD-101', proximity: 1, rationale: '', path: [] }],
  update_summary: [],
};

function mockApi() {
  const calls: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      calls.push(url);
      if (url.startsWith('/api/v1/events/facets')) return jsonResponse({ type: [{ value: 'ENDPOINT_CHANGED', count: 1 }], source: [{ value: 'ctgov', count: 3 }] });
      if (url.startsWith('/api/v1/events')) return jsonResponse({ items: [EVENT], total: 1, limit: 50, offset: 0, next_offset: null });
      if (url.startsWith('/api/v1/saved-views')) return jsonResponse({ items: [], total: 0, limit: 200, offset: 0, next_offset: null });
      return jsonResponse({});
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe('FeedPage', () => {
  it('initialises filters from the URL and sends them to the API', async () => {
    const calls = mockApi();
    renderWithProviders(<FeedPage />, { route: '/feed?band=High+Priority&sort=score&q=NCT' });
    expect(await screen.findByRole('link', { name: /NCT99000001/ })).toBeInTheDocument();
    const evCall = calls.find((c) => c.startsWith('/api/v1/events?')) ?? '';
    const sp = new URLSearchParams(evCall.split('?')[1]);
    expect(sp.getAll('band')).toEqual(['High Priority']);
    expect(sp.get('sort')).toBe('score');
    expect(sp.get('q')).toBe('NCT');
    expect(screen.getByRole('checkbox', { name: 'High Priority' })).toBeChecked();
    expect(screen.getByLabelText('Search titles')).toHaveValue('NCT');
    // row shows score + band text label, type, affected asset, source, status, review
    expect(screen.getAllByText('Executive Alert').length).toBeGreaterThan(0);
    expect(screen.getByText('XD-101')).toBeInTheDocument();
  });

  it('writes filter changes to the URL (bookmarkable) and refetches', async () => {
    const calls = mockApi();
    renderWithProviders(<FeedPage />, { route: '/feed' });
    await screen.findByRole('link', { name: /NCT99000001/ });
    await userEvent.click(screen.getByRole('checkbox', { name: 'Executive Alert' }));
    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/feed?band=Executive+Alert'));
    await userEvent.selectOptions(screen.getByLabelText('Sort'), 'score');
    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/feed?band=Executive+Alert&sort=score'));
    await userEvent.type(screen.getByLabelText('Minimum score'), '70');
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(new URLSearchParams(screen.getByTestId('location').textContent?.split('?')[1]).get('min_score')).toBe('70'));
    await waitFor(() => expect(calls.some((c) => c.includes('band=Executive+Alert') && c.includes('min_score=70') && c.includes('sort=score'))).toBe(true));
  });
});
