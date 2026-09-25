import { useEffect, useId, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/endpoints';
import type { EntitySearchHit } from '../api/types';

function useDebounced<T>(v: T, ms = 250): T {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = window.setTimeout(() => setD(v), ms);
    return () => window.clearTimeout(t);
  }, [v, ms]);
  return d;
}

/** Accessible combobox over GET /entities/search. */
export function EntityPicker({
  label,
  type,
  onSelect,
  placeholder = 'Type at least 2 characters',
}: {
  label: string;
  type?: string;
  onSelect: (hit: EntitySearchHit) => void;
  placeholder?: string;
}) {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const dq = useDebounced(q.trim());
  const id = useId();
  const search = useQuery({
    queryKey: ['entity-search', dq, type],
    queryFn: () => api.searchEntities(dq, type || undefined, 15),
    enabled: dq.length >= 2,
    staleTime: 30_000,
  });
  const hits = search.data ?? [];
  const choose = (h: EntitySearchHit) => {
    onSelect(h);
    setQ('');
    setOpen(false);
  };
  return (
    <div className="field" style={{ position: 'relative' }}>
      <label htmlFor={`${id}-input`}>{label}</label>
      <input
        id={`${id}-input`}
        type="search"
        role="combobox"
        aria-expanded={open && hits.length > 0}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        aria-activedescendant={open && hits[active] ? `${id}-opt-${active}` : undefined}
        value={q}
        placeholder={placeholder}
        autoComplete="off"
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setOpen(true);
            setActive((a) => Math.min(a + 1, hits.length - 1));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === 'Enter' && open && hits[active]) {
            e.preventDefault();
            choose(hits[active]);
          } else if (e.key === 'Escape') setOpen(false);
        }}
      />
      {open && dq.length >= 2 ? (
        <ul id={`${id}-list`} role="listbox" className="menu" style={{ left: 0, right: 'auto', width: '100%', maxHeight: 280, overflowY: 'auto', listStyle: 'none' }}>
          {search.isLoading ? <li className="small muted" style={{ padding: 8 }}>Searching...</li> : null}
          {!search.isLoading && hits.length === 0 ? <li className="small muted" style={{ padding: 8 }}>No matches</li> : null}
          {hits.map((h, i) => (
            <li
              key={`${h.type}-${h.id}`}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              className="menu-item"
              style={i === active ? { background: 'var(--surface-2)' } : undefined}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(h);
              }}
            >
              <span className="badge badge-neutral">{h.type}</span>
              <span className="truncate">{h.name}</span>
              {h.matched_alias && h.matched_alias !== h.name ? <span className="tiny muted">({h.matched_alias})</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
