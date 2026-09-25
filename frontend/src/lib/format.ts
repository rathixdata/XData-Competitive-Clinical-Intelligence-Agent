const dateFmt = new Intl.DateTimeFormat('en-GB', { year: 'numeric', month: 'short', day: '2-digit' });
const dateTimeFmt = new Intl.DateTimeFormat('en-GB', {
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
});

function parse(v: string | null | undefined): Date | null {
  if (!v) return null;
  // Bare dates (YYYY-MM-DD) are calendar dates: render them without timezone shifting.
  const d = /^\d{4}-\d{2}-\d{2}$/.test(v) ? new Date(`${v}T00:00:00`) : new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtDate(v: string | null | undefined): string {
  const d = parse(v);
  return d ? dateFmt.format(d) : '-';
}

export function fmtDateTime(v: string | null | undefined): string {
  const d = parse(v);
  return d ? dateTimeFmt.format(d) : '-';
}

export function fmtRelative(v: string | null | undefined, now: Date = new Date()): string {
  const d = parse(v);
  if (!d) return '-';
  const diff = (now.getTime() - d.getTime()) / 1000;
  const abs = Math.abs(diff);
  const fut = diff < 0;
  const unit = (n: number, u: string) => `${n} ${u}${n === 1 ? '' : 's'}`;
  let s: string;
  if (abs < 60) s = 'just now';
  else if (abs < 3600) s = unit(Math.round(abs / 60), 'minute');
  else if (abs < 86400) s = unit(Math.round(abs / 3600), 'hour');
  else if (abs < 86400 * 45) s = unit(Math.round(abs / 86400), 'day');
  else return fmtDate(v);
  if (s === 'just now') return s;
  return fut ? `in ${s}` : `${s} ago`;
}

/** Render any backend value (scalar, list, object) as readable text. */
export function fmtValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '-';
  if (Array.isArray(v)) return v.length ? v.map((x) => fmtValue(x)).join('; ') : '-';
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>;
    if ('measure' in o) return String(o.measure);
    if ('value' in o && Object.keys(o).length <= 3) return fmtValue(o.value);
    return Object.entries(o)
      .map(([k, x]) => `${k}: ${fmtValue(x)}`)
      .join(', ');
  }
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString('en-US') : v.toLocaleString('en-US', { maximumFractionDigits: 2 });
  return String(v);
}

export function humanize(key: string | null | undefined): string {
  if (!key) return '-';
  const s = key.replace(/_/g, ' ').toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return '-';
  return `${(v * 100).toFixed(digits)}%`;
}

export function isoDay(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : '-';
}
