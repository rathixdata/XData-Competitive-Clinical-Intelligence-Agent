import { createContext, useContext } from 'react';

export type ToastKind = 'info' | 'error';
export interface ToastApi {
  notify: (message: string, kind?: ToastKind) => void;
}

export const ToastContext = createContext<ToastApi>({ notify: () => undefined });

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

export function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  return 'Something went wrong.';
}
