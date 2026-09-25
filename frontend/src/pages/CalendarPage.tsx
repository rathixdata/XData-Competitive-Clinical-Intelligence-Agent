import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { api } from '../api/endpoints';
import type { Catalyst } from '../api/types';
import { BasisBadge, ChangedDateBadge } from '../components/Badges';
import { Modal } from '../components/Dialog';
import { EmptyState, QueryView } from '../components/States';
import { useLandscape } from '../state/landscapeContext';
import { anchorDate, catalystDate, previousDate } from '../lib/catalyst';
import { fmtValue, humanize, isoDay } from '../lib/format';

type Mode = 'month' | 'quarter';
const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const monthFmt = new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric' });

function periodOf(mode: Mode, anchor: Date): { start: Date; end: Date; label: string } {
  if (mode === 'month') {
    const start = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
    const end = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
    return { start, end, label: monthFmt.format(start) };
  }
  const q = Math.floor(anchor.getMonth() / 3);
  const start = new Date(anchor.getFullYear(), q * 3, 1);
  const end = new Date(anchor.getFullYear(), q * 3 + 3, 0);
  return { start, end, label: `Q${q + 1} ${anchor.getFullYear()}` };
}

function parseAnchor(s: string | null): Date {
  if (s && /^\d{4}-\d{2}$/.test(s)) {
    const [y, m] = s.split('-').map(Number);
    return new Date(y, m - 1, 1);
  }
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function CatalystChip({ c, onOpen }: { c: Catalyst; onOpen: (c: Catalyst) => void }) {
  const inferred = c.date_basis === 'INFERRED';
  return (
    <button
      type="button"
      className={`cal-item ${inferred ? 'inferred' : 'sourced'}`}
      onClick={() => onOpen(c)}
      title={`${c.title} (${inferred ? 'model-inferred window' : 'sourced date'})`}
      aria-label={`${c.title}. ${inferred ? 'Inferred window' : 'Sourced date'} ${catalystDate(c)}${c.changed ? ', date changed' : ''}`}
    >
      {inferred ? 'Inferred: ' : 'Sourced: '}
      {c.changed ? '(changed) ' : ''}
      {c.asset_name ?? c.nct_id ?? ''} {humanize(c.event_type)}
    </button>
  );
}

function MonthGrid({ start, items, onOpen }: { start: Date; items: Catalyst[]; onOpen: (c: Catalyst) => void }) {
  const first = new Date(start);
  const offset = (first.getDay() + 6) % 7;
  const gridStart = new Date(first.getFullYear(), first.getMonth(), 1 - offset);
  const days = Array.from({ length: 42 }, (_, i) => new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i));
  const byDay = new Map<string, Catalyst[]>();
  for (const c of items) {
    const a = anchorDate(c);
    if (!a) continue;
    byDay.set(a, [...(byDay.get(a) ?? []), c]);
  }
  const today = isoDay(new Date());
  return (
    <div className="cal-grid month" role="grid" aria-label={`Month view, ${monthFmt.format(start)}`}>
      <div role="row" style={{ display: 'contents' }}>
        {DOW.map((d) => (
          <div key={d} className="cal-dow" role="columnheader">
            {d}
          </div>
        ))}
      </div>
      {Array.from({ length: 6 }, (_, w) => (
        <div role="row" key={w} style={{ display: 'contents' }}>
          {days.slice(w * 7, w * 7 + 7).map((d) => {
            const key = isoDay(d);
            const inMonth = d.getMonth() === start.getMonth();
            const list = byDay.get(key) ?? [];
            return (
              <div key={key} role="gridcell" className={`cal-cell ${inMonth ? '' : 'outside'} ${key === today ? 'today' : ''}`} aria-label={`${key}${list.length ? `, ${list.length} catalyst(s)` : ''}`}>
                <span className="cal-daynum">{d.getDate()}</span>
                {list.map((c) => (
                  <CatalystChip key={c.id} c={c} onOpen={onOpen} />
                ))}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function Agenda({ start, end, items, onOpen, columns }: { start: Date; end: Date; items: Catalyst[]; onOpen: (c: Catalyst) => void; columns: boolean }) {
  const months: Date[] = [];
  for (let m = new Date(start); m <= end; m = new Date(m.getFullYear(), m.getMonth() + 1, 1)) months.push(m);
  return (
    <div className={columns ? 'grid grid-3' : 'stack'}>
      {months.map((m) => {
        const key = `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, '0')}`;
        const list = items.filter((c) => (anchorDate(c) ?? '').startsWith(key));
        return (
          <section key={key} className="card" aria-label={monthFmt.format(m)}>
            <h3>{monthFmt.format(m)}</h3>
            {list.length === 0 ? (
              <p className="small muted">No catalysts.</p>
            ) : (
              <ul className="list-plain">
                {list.map((c) => (
                  <li key={c.id} className="stack-sm">
                    <div className="row">
                      <strong className="nowrap">{catalystDate(c)}</strong>
                      <BasisBadge basis={c.date_basis} />
                      {c.changed ? <ChangedDateBadge previous={previousDate(c.previous)} /> : null}
                    </div>
                    <button type="button" className="btn btn-ghost btn-sm" style={{ justifyContent: 'flex-start', height: 'auto', whiteSpace: 'normal', textAlign: 'left' }} onClick={() => onOpen(c)}>
                      {c.title}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}

export function CalendarPage() {
  const { landscapeId } = useLandscape();
  const [sp, setSp] = useSearchParams();
  const mode: Mode = sp.get('mode') === 'quarter' ? 'quarter' : 'month';
  const anchor = parseAnchor(sp.get('at'));
  const basis = sp.get('basis') ?? '';
  const changedOnly = sp.get('changed') === '1';
  const period = periodOf(mode, anchor);
  const [open, setOpen] = useState<Catalyst | null>(null);
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    setSp(next, { replace: true });
  };
  const shift = (dir: number) => {
    const step = mode === 'month' ? 1 : 3;
    const d = new Date(anchor.getFullYear(), anchor.getMonth() + dir * step, 1);
    set({ at: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}` });
  };
  const query = useMemo(
    () => ({ from: isoDay(period.start), to: isoDay(period.end), landscape_id: landscapeId, basis: basis || undefined, changed_only: changedOnly || undefined }),
    [period.start, period.end, landscapeId, basis, changedOnly],
  );
  const q = useQuery({ queryKey: ['catalysts', query], queryFn: () => api.catalysts(query) });

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Catalyst calendar</h1>
          <p>Sourced dates are reported by a source record; inferred windows are model heuristics.</p>
        </div>
        <div className="seg" role="group" aria-label="Calendar view">
          <button type="button" aria-pressed={mode === 'month'} onClick={() => set({ mode: null })}>
            Month
          </button>
          <button type="button" aria-pressed={mode === 'quarter'} onClick={() => set({ mode: 'quarter' })}>
            Quarter
          </button>
        </div>
      </div>
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="row-between">
          <div className="row">
            <button type="button" className="btn btn-icon" onClick={() => shift(-1)} aria-label={`Previous ${mode}`}>
              <ChevronLeft size={16} aria-hidden />
            </button>
            <h2 style={{ margin: 0, minWidth: 170, textAlign: 'center' }} aria-live="polite">
              {period.label}
            </h2>
            <button type="button" className="btn btn-icon" onClick={() => shift(1)} aria-label={`Next ${mode}`}>
              <ChevronRight size={16} aria-hidden />
            </button>
            <button type="button" className="btn btn-sm" onClick={() => set({ at: null })}>
              Today
            </button>
          </div>
          <div className="row">
            <label htmlFor="cal-basis" className="small strong">
              Date basis
            </label>
            <select id="cal-basis" style={{ width: 160 }} value={basis} onChange={(e) => set({ basis: e.target.value || null })}>
              <option value="">Sourced and inferred</option>
              <option value="SOURCED">Sourced only</option>
              <option value="INFERRED">Inferred only</option>
            </select>
            <label className="checkbox">
              <input type="checkbox" checked={changedOnly} onChange={(e) => set({ changed: e.target.checked ? '1' : null })} />
              Changed dates only
            </label>
          </div>
        </div>
        <div className="legend" style={{ marginTop: 10 }} aria-label="Legend">
          <span>Legend:</span>
          <BasisBadge basis="SOURCED" /> <span>{q.data?.legend?.SOURCED ?? 'Date reported by the source record'}</span>
          <BasisBadge basis="INFERRED" /> <span>{q.data?.legend?.INFERRED ?? 'Model-inferred window (heuristic)'}</span>
          <ChangedDateBadge previous={null} /> <span>Date moved; previous date shown</span>
        </div>
      </div>
      <QueryView query={q} loadingLabel="Loading catalysts">
        {(d) =>
          d.items.length === 0 ? (
            <div className="card">
              <EmptyState title={`No catalysts in ${period.label}`}>Try another period or remove filters.</EmptyState>
            </div>
          ) : mode === 'month' ? (
            <div className="stack">
              <MonthGrid start={period.start} items={d.items} onOpen={setOpen} />
              <details className="card">
                <summary>List view ({d.items.length} catalysts)</summary>
                <Agenda start={period.start} end={period.end} items={d.items} onOpen={setOpen} columns={false} />
              </details>
            </div>
          ) : (
            <Agenda start={period.start} end={period.end} items={d.items} onOpen={setOpen} columns />
          )
        }
      </QueryView>
      <Modal open={Boolean(open)} onClose={() => setOpen(null)} title={open?.title ?? 'Catalyst'}>
        {open ? (
          <div className="stack">
            <div className="row">
              <BasisBadge basis={open.date_basis} />
              {open.confidence ? <span className="badge badge-neutral">Confidence: {open.confidence}</span> : null}
              {open.changed ? <ChangedDateBadge previous={previousDate(open.previous)} /> : null}
            </div>
            <dl className="kv">
              <dt>{open.date_basis === 'INFERRED' ? 'Inferred window' : 'Expected date'}</dt>
              <dd>
                {catalystDate(open)} {open.date_precision ? `(precision: ${open.date_precision})` : ''}
              </dd>
              {open.changed ? (
                <>
                  <dt>Previous date</dt>
                  <dd>{previousDate(open.previous) ?? '-'}</dd>
                </>
              ) : null}
              <dt>Type</dt>
              <dd>{humanize(open.event_type)}</dd>
              {open.asset_name ? (
                <>
                  <dt>Asset</dt>
                  <dd>{open.asset_id ? <Link to={`/assets/${open.asset_id}`}>{open.asset_name}</Link> : open.asset_name}</dd>
                </>
              ) : null}
              {open.nct_id ? (
                <>
                  <dt>Trial</dt>
                  <dd>{open.nct_id}</dd>
                </>
              ) : null}
              {open.evidence
                ? Object.entries(open.evidence)
                    .filter(([k]) => !['snapshot_id', 'source_document_id'].includes(k))
                    .map(([k, v]) => (
                      <div key={k} style={{ display: 'contents' }}>
                        <dt>{humanize(k)}</dt>
                        <dd>{k === 'uri' ? <a href={String(v)} target="_blank" rel="noreferrer noopener">{String(v)}</a> : fmtValue(v)}</dd>
                      </div>
                    ))
                : null}
            </dl>
            {open.date_basis === 'INFERRED' ? (
              <p className="small muted">This window is a model heuristic, not a company or registry disclosure. Treat it as a hypothesis.</p>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </>
  );
}
