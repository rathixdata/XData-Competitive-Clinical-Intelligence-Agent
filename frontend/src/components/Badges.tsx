import { AlertTriangle, CalendarClock, CheckCircle2, Clock, History, Sparkles, UserCheck } from 'lucide-react';
import type { Band } from '../api/types';
import { BAND_DESCRIPTION, bandClass } from './bandMeta';
import { fmtRelative } from '../lib/format';

/** Materiality band: colour + always the text label (never colour alone). */
export function BandBadge({ band, score }: { band: Band | string; score?: number | null }) {
  const desc = BAND_DESCRIPTION[band as Band] ?? band;
  return (
    <span className={`band ${bandClass(band)}`} title={desc}>
      <span className="band-dot" aria-hidden />
      {score !== undefined && score !== null ? <span className="score">{score.toFixed(0)}</span> : null}
      <span>{band}</span>
    </span>
  );
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  const tone =
    status === 'escalated' || status === 'blocked' || status === 'failed' || status === 'dead'
      ? 'badge-danger'
      : status === 'acknowledged' || status === 'approved' || status === 'distributed' || status === 'healthy' || status === 'succeeded' || status === 'sent' || status === 'active'
        ? 'badge-success'
        : status === 'in_review' || status === 'pending' || status === 'running' || status === 'stale' || status === 'draft'
          ? 'badge-warning'
          : 'badge-neutral';
  return <span className={`badge ${tone}`}>{status.replace(/_/g, ' ')}</span>;
}

/** Review status: machine output vs analyst-reviewed / approved, plus a human-edited marker. */
export function ReviewBadge({ status, humanEdited }: { status: string | null | undefined; humanEdited?: boolean }) {
  if (!status) return null;
  const reviewed = status === 'Analyst-reviewed' || status === 'Approved';
  return (
    <span className="row" style={{ gap: 4, display: 'inline-flex' }}>
      {reviewed ? (
        <span className="badge badge-human" title="A human analyst reviewed or approved this output">
          <UserCheck size={12} aria-hidden />
          {status}
        </span>
      ) : (
        <span className="badge badge-neutral" title="Machine-generated; not yet reviewed by an analyst">
          <Sparkles size={12} aria-hidden />
          Machine - not reviewed
        </span>
      )}
      {humanEdited ? (
        <span className="badge badge-human" title="Narrative text was edited by an analyst">
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
      <span className="badge badge-inferred" title="Model-inferred window (heuristic), not reported by a source">
        <Sparkles size={12} aria-hidden />
        Inferred
      </span>
    );
  }
  return (
    <span className="badge badge-sourced" title="Date reported by the source record">
      <CheckCircle2 size={12} aria-hidden />
      Sourced
    </span>
  );
}

export function StaleBadge({ label = 'Stale data', since }: { label?: string; since?: string | null }) {
  return (
    <span className="badge badge-warning" title="Source freshness below its service level; data may be outdated">
      <Clock size={12} aria-hidden />
      {label}
      {since ? ` - last success ${fmtRelative(since)}` : ''}
    </span>
  );
}

export function IndirectBadge() {
  return (
    <span className="badge badge-warning" title="Cross-trial comparisons are indirect">
      <AlertTriangle size={12} aria-hidden />
      Indirect comparison
    </span>
  );
}

export function ChangedDateBadge({ previous }: { previous: string | null | undefined }) {
  return (
    <span className="badge badge-warning">
      <History size={12} aria-hidden />
      Changed{previous ? ` - was ${previous}` : ''}
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
  return <span className={`badge ${tone}`}>Confidence: {confidence}</span>;
}
