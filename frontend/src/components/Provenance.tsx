import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import type { Provenance } from '../api/types';
import { fmtDateTime } from '../lib/format';
import { provenanceText } from '../lib/provenance';

/** Matrix/compare cell whose provenance appears on hover AND keyboard focus (WCAG 1.4.13). */
export function ProvenanceCell({ provenance, children, indirect = true }: { provenance: Provenance | null; children: ReactNode; indirect?: boolean }) {
  const [pos, setPos] = useState<CSSProperties | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const id = useId();
  const open = pos !== null;
  // Fixed positioning so the popover is never clipped by scrollable table containers.
  const show = () => {
    const r = btn.current?.getBoundingClientRect();
    if (!r) return;
    const width = Math.min(300, window.innerWidth - 16);
    const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8));
    const below = r.bottom + 6;
    const style: CSSProperties = { position: 'fixed', left, width, top: below };
    if (below + 180 > window.innerHeight && r.top > 200) {
      delete style.top;
      style.bottom = window.innerHeight - r.top + 6;
    }
    setPos(style);
  };
  const hide = () => setPos(null);
  useEffect(() => {
    if (!open) return;
    const onScroll = () => setPos(null);
    window.addEventListener('scroll', onScroll, true);
    return () => window.removeEventListener('scroll', onScroll, true);
  }, [open]);
  return (
    <span
      className="pop-anchor"
      onMouseEnter={show}
      onMouseLeave={hide}
    >
      <button
        ref={btn}
        type="button"
        className="cell-btn"
        aria-describedby={open ? id : undefined}
        onFocus={show}
        onBlur={hide}
        onKeyDown={(e) => {
          if (e.key === 'Escape') hide();
        }}
        onClick={() => (open ? hide() : show())}
      >
        {children}
        <span className="sr-only">. {provenanceText(provenance)}</span>
      </button>
      {open ? (
        <span className="pop" role="tooltip" id={id} style={pos ?? undefined}>
          <dl className="kv" style={{ gridTemplateColumns: 'max-content 1fr' }}>
            <dt>Source</dt>
            <dd>{provenance?.source ?? 'unknown'}</dd>
            {provenance?.field ? (
              <>
                <dt>Field</dt>
                <dd>{provenance.field}</dd>
              </>
            ) : null}
            {provenance?.snapshot_version !== undefined ? (
              <>
                <dt>Snapshot</dt>
                <dd>v{provenance.snapshot_version}</dd>
              </>
            ) : null}
            {provenance?.profile_version !== undefined ? (
              <>
                <dt>Profile</dt>
                <dd>v{provenance.profile_version}</dd>
              </>
            ) : null}
            <dt>{provenance?.retrieved_at ? 'Retrieved' : 'Updated'}</dt>
            <dd>{fmtDateTime(provenance?.retrieved_at ?? provenance?.updated_at)}</dd>
            {provenance?.uri ? (
              <>
                <dt>Record</dt>
                <dd style={{ overflowWrap: 'anywhere' }}>{provenance.uri}</dd>
              </>
            ) : null}
          </dl>
          {indirect ? <span style={{ display: 'block', marginTop: 6 }}>Note: cross-trial comparisons are indirect.</span> : null}
        </span>
      ) : null}
    </span>
  );
}
