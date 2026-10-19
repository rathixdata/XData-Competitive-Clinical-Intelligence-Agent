import { useState } from 'react';
import { AlertTriangle, CalendarClock, CheckCircle2, ChevronDown, Clock, History, Sparkles, UserCheck } from 'lucide-react';
import type { Band } from '../api/types';
import { BAND_DESCRIPTION, BAND_INFO, bandClass } from './bandMeta';
import { fmtRelative } from '../lib/format';
import { CONFIDENCE_DESCRIPTIONS, REVIEW_LABELS, STATUS_DESCRIPTIONS, statusLabel } from '../lib/labels';

/** Priority band: colour + always the text label (never colour alone); the number is the 0-100 importance score. */
export function BandBadge({ band, score }: { band: Band | string; score?: number | null }) {
  const desc = BAND_DESCRIPTION[band as Band] ?? band;
  const hasScore = score !== undefined && score !== null;
  return (
    <span className={`band ${bandClass(band)}`} title={hasScore ? `Importance score ${score.toFixed(0)}/100. ${desc}` : desc}>
      <span className="band-dot" aria-hidden />
      {hasScore ? (
        <>
          <span className="sr-only">Importance score</span>
          <span className="score">{score.toFixed(0)}</span>
        </>
      ) : null}
      <span>{band}</span>
    </span>
  );
}

/** Legend explaining the priority bands and what to do with each. */
export function BandLegend({ thresholds, defaultOpen = false }: { thresholds?: Record<string, number>; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="band-legend">
      <button type="button" className="link-btn small" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <ChevronDown size={14} aria-hidden className={open ? 'rot-180' : undefined} /> What do the priority levels mean?
      </button>
      {open ? (
        <div className="table-wrap" style={{ marginTop: 8 }}>
          <table className="table table-compact">
            <caption className="sr-only">Priority levels: what they mean and what to do</caption>
            <thead>
              <tr>
                <th scope="col">Priority</th>
                <th scope="col">Importance score</th>
                <th scope="col">What it means</th>
                <th scope="col">What to do</th>
              </tr>
            </thead>
            <tbody>
              {BAND_INFO.map((b) => {
                const min = thresholds?.[b.band] ?? b.min;
                return (
                  <tr key={b.band}>
                    <td>
                      <BandBadge band={b.band} />
                    </td>
                    <td className="nowrap">{b.band === 'Archive' ? `below ${thresholds?.Feed ?? 30}` : `${min} or more`}</td>
                    <td>{b.meaning}</td>
                    <td>{b.action}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="tiny muted" style={{ margin: '6px 0 0' }}>
            The importance score (0-100) combines how relevant the change is to your portfolio, how big the change is, how close the competitor is to your drug, timing and novelty.
          </p>
        </div>
      ) : null}
    </div>
  );
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  const tone =
    status === 'escalated' || status === 'blocked' || status === 'failed' || status === 'failing' || status === 'dead'
      ? 'badge-danger'
      : status === 'acknowledged' || status === 'approved' || status === 'distributed' || status === 'healthy' || status === 'succeeded' || status === 'sent' || status === 'active'
        ? 'badge-success'
        : status === 'in_review' || status === 'pending' || status === 'running' || status === 'stale' || status === 'draft' || status === 'never_run'
          ? 'badge-warning'
          : status === 'published'
            ? 'badge-info'
            : 'badge-neutral';
  return (
    <span className={`badge ${tone}`} title={STATUS_DESCRIPTIONS[status]}>
      {statusLabel(status)}
    </span>
  );
}

/** Review status: AI output vs analyst-reviewed / approved, plus a human-edited marker. */
export function ReviewBadge({ status, humanEdited }: { status: string | null | undefined; humanEdited?: boolean }) {
  if (!status) return null;
  const reviewed = status === 'Analyst-reviewed' || status === 'Approved';
  const meta = REVIEW_LABELS[status] ?? REVIEW_LABELS.Machine;
  return (
    <span className="row" style={{ gap: 4, display: 'inline-flex' }}>
      {reviewed ? (
        <span className="badge badge-human" title={meta.description}>
          <UserCheck size={12} aria-hidden />
          {status === 'Approved' ? meta.label : status}
        </span>
      ) : (
        <span className="badge badge-neutral" title={meta.description}>
          <Sparkles size={12} aria-hidden />
          {meta.label}
          <span className="sr-only"> ({meta.description})</span>
        </span>
      )}
      {humanEdited ? (
        <span className="badge badge-human" title="The AI summary text was edited by an analyst">
          <UserCheck size={12} aria-hidden />
          Human-edited
        </span>
      ) : null}
    </span>
  );
}

export function BasisBadge({ basis }: { basis: 'SOURCED' | 'INFERRED' | string }) {
  if (basis === 'INFERRED') {
    return (
      <span className="badge badge-inferred" title="Estimated by the system from patterns (not announced by the company or registry). Treat as a hypothesis.">
        <Sparkles size={12} aria-hidden />
        Estimated
      </span>
    );
  }
  return (
    <span className="badge badge-sourced" title="Date published in the source record (registry, company or regulator)">
      <CheckCircle2 size={12} aria-hidden />
      Reported date
    </span>
  );
}

export function StaleBadge({ label = 'May be out of date', since }: { label?: string; since?: string | null }) {
  return (
    <span className="badge badge-warning" title="The source behind this value has not been checked recently; it may be outdated">
      <Clock size={12} aria-hidden />
      {label}
      {since ? ` - last updated ${fmtRelative(since)}` : ''}
    </span>
  );
}

export function IndirectBadge() {
  return (
    <span className="badge badge-warning" title="Values come from different trials, so they cannot be compared head-to-head">
      <AlertTriangle size={12} aria-hidden />
      Indirect comparison
    </span>
  );
}

export function ChangedDateBadge({ previous }: { previous: string | null | undefined }) {
  return (
    <span className="badge badge-warning" title="This date has moved since we first saw it">
      <History size={12} aria-hidden />
      Date moved{previous ? ` - was ${previous}` : ''}
    </span>
  );
}

export function WindowBadge() {
  return (
    <span className="badge badge-neutral">
      <CalendarClock size={12} aria-hidden />
      Window
    </span>
  );
}

export function ConfidenceBadge({ confidence }: { confidence: string | null | undefined }) {
  if (!confidence) return null;
  const tone =
    confidence === 'Verified' || confidence === 'High'
      ? 'badge-success'
      : confidence === 'Medium'
        ? 'badge-info'
        : confidence === 'Low'
          ? 'badge-warning'
          : 'badge-neutral';
  return (
    <span className={`badge ${tone}`} title={CONFIDENCE_DESCRIPTIONS[confidence]}>
      Confidence: {confidence}
    </span>
  );
}
