import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { filtersToObject, objectToFilters, parseFeedParams, toApiQuery, toSearchParams, useFeedFilters } from './feedFilters';

describe('feed filter <-> URL serialisation', () => {
  it('round-trips multi and single params', () => {
    const sp = new URLSearchParams('band=Executive+Alert&band=High+Priority&event_type=ENDPOINT_CHANGED&min_score=50&q=NCT99000001&sort=score&personalize=true');
    const f = parseFeedParams(sp);
    expect(f.band).toEqual(['Executive Alert', 'High Priority']);
    expect(f.event_type).toEqual(['ENDPOINT_CHANGED']);
    expect(f.status).toEqual([]);
    expect(f.min_score).toBe('50');
    expect(f.sort).toBe('score');
    expect(parseFeedParams(toSearchParams(f))).toEqual(f);
  });

  it('maps to the GET /events query (inclusive end date, display-only keys dropped)', () => {
    const f = parseFeedParams(new URLSearchParams('to=2026-09-30&company_id=c1&company_name=Acme&personalize=true'));
    const q = toApiQuery(f, 'ls-1');
    expect(q.to).toBe('2026-09-30T23:59:59');
    expect(q.landscape_id).toBe('ls-1');
    expect(q.company_id).toBe('c1');
    expect(q).not.toHaveProperty('company_name');
    expect(q.personalize).toBe(true);
    expect(q.sort).toBe('date');
  });

  it('serialises for saved views and restores them', () => {
    const f = parseFeedParams(new URLSearchParams('band=Feed&band=Archive&q=x&offset=50'));
    const o = filtersToObject(f);
    expect(o).toEqual({ band: ['Feed', 'Archive'], q: 'x' });
    expect(objectToFilters(o).band).toEqual(['Feed', 'Archive']);
  });
});

describe('useFeedFilters', () => {
  function setup(initial: string) {
    let loc = '';
    function Probe() {
      const l = useLocation();
      loc = l.search;
      return null;
    }
    const wrapper = ({ children }: { children: ReactNode }) => (
      <MemoryRouter initialEntries={[initial]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        {children}
        <Probe />
      </MemoryRouter>
    );
    const hook = renderHook(() => useFeedFilters(), { wrapper });
    return { hook, loc: () => loc };
  }

  it('reads state from the URL and writes every change back to it', () => {
    const { hook, loc } = setup('/feed?band=Feed&offset=50');
    expect(hook.result.current[0].band).toEqual(['Feed']);
    act(() => hook.result.current[1]({ band: ['Feed', 'Executive Alert'], min_score: '70' }));
    const sp = new URLSearchParams(loc());
    expect(sp.getAll('band')).toEqual(['Feed', 'Executive Alert']);
    expect(sp.get('min_score')).toBe('70');
    // changing a filter resets pagination
    expect(sp.get('offset')).toBeNull();
    expect(hook.result.current[0].min_score).toBe('70');
  });

  it('keeps an explicit offset and resets everything', () => {
    const { hook, loc } = setup('/feed?q=abc');
    act(() => hook.result.current[1]({ offset: '50' }));
    expect(new URLSearchParams(loc()).get('offset')).toBe('50');
    expect(new URLSearchParams(loc()).get('q')).toBe('abc');
    act(() => hook.result.current[2]());
    expect(loc()).toBe('');
  });
});
