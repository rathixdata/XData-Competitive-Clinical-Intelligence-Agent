import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { ToastContext, type ToastKind } from '../lib/toastContext';

interface Toast {
  id: number;
  message: string;
  kind: ToastKind;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const notify = useCallback(
    (message: string, kind: ToastKind = 'info') => {
      const id = ++seq.current;
      setToasts((t) => [...t.slice(-3), { id, message, kind }]);
      window.setTimeout(() => dismiss(id), kind === 'error' ? 9000 : 5000);
    },
    [dismiss],
  );
  const value = useMemo(() => ({ notify }), [notify]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind === 'error' ? 'toast-error' : ''}`} role={t.kind === 'error' ? 'alert' : undefined}>
            <span style={{ flex: 1 }}>{t.message}</span>
            <button type="button" className="btn btn-ghost btn-sm" style={{ color: '#fff' }} onClick={() => dismiss(t.id)} aria-label="Dismiss notification">
              <X size={14} aria-hidden />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
