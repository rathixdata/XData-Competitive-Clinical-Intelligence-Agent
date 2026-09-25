import type { ReactNode } from 'react';
import { AlertCircle, Inbox } from 'lucide-react';
import { ApiError } from '../api/client';

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="spinner" aria-hidden />
      <span>{label}...</span>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state">
      <Inbox size={26} aria-hidden />
      <strong>{title}</strong>
      {children ? <div className="small">{children}</div> : null}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : 'Something went wrong.';
  const forbidden = error instanceof ApiError && error.isForbidden;
  return (
    <div className="state state-error" role="alert">
      <AlertCircle size={26} aria-hidden />
      <strong>{forbidden ? 'You do not have permission to view this.' : 'Could not load data'}</strong>
      <span className="small">{msg}</span>
      {onRetry && !forbidden ? (
        <button type="button" className="btn btn-sm" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function InlineError({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="banner banner-danger" role="alert">
      <AlertCircle size={18} aria-hidden />
      <p>{msg}</p>
    </div>
  );
}

/** Query-state switcher: loading / error / empty / content. */
export function QueryView<T>({
  query,
  empty,
  isEmpty,
  children,
  loadingLabel,
}: {
  query: { data: T | undefined; isLoading: boolean; error: unknown; refetch: () => unknown };
  empty?: ReactNode;
  isEmpty?: (d: T) => boolean;
  children: (d: T) => ReactNode;
  loadingLabel?: string;
}) {
  if (query.isLoading) return <Loading label={loadingLabel} />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.data === undefined) return null;
  if (isEmpty?.(query.data)) return <>{empty ?? <EmptyState title="Nothing to show" />}</>;
  return <>{children(query.data)}</>;
}
