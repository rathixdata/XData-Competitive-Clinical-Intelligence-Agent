import { useEffect, useId, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

const FOCUSABLE = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

function useDialogBehaviour(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const first = el?.querySelector<HTMLElement>('[data-autofocus]') ?? el?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        closeRef.current();
      } else if (e.key === 'Tab' && el) {
        const items = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((x) => x.offsetParent !== null || x === document.activeElement);
        if (items.length === 0) return;
        const firstEl = items[0];
        const lastEl = items[items.length - 1];
        if (e.shiftKey && document.activeElement === firstEl) {
          e.preventDefault();
          lastEl.focus();
        } else if (!e.shiftKey && document.activeElement === lastEl) {
          e.preventDefault();
          firstEl.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
      prev?.focus?.();
    };
  }, [open]);
  return ref;
}

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}

export function Modal({ open, onClose, title, children, footer, wide }: DialogProps) {
  const ref = useDialogBehaviour(open, onClose);
  const id = useId();
  if (!open) return null;
  return createPortal(
    <>
      <div className="overlay" onClick={onClose} aria-hidden />
      <div ref={ref} className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby={id}>
        <div className="modal-head">
          <h2 id={id}>{title}</h2>
          <button type="button" className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close dialog">
            <X size={18} aria-hidden />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-foot">{footer}</div> : null}
      </div>
    </>,
    document.body,
  );
}

export function Drawer({ open, onClose, title, children, footer }: DialogProps) {
  const ref = useDialogBehaviour(open, onClose);
  const id = useId();
  if (!open) return null;
  return createPortal(
    <>
      <div className="overlay" onClick={onClose} aria-hidden />
      <aside ref={ref} className="drawer" role="dialog" aria-modal="true" aria-labelledby={id}>
        <div className="drawer-head">
          <h2 id={id}>{title}</h2>
          <button type="button" className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close panel">
            <X size={18} aria-hidden />
          </button>
        </div>
        <div className="drawer-body">{children}</div>
        {footer ? <div className="modal-foot">{footer}</div> : null}
      </aside>
    </>,
    document.body,
  );
}
