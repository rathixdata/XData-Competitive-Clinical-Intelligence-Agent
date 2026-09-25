/**
 * Access-token storage: in memory, mirrored to sessionStorage so a reload in the same tab keeps
 * the session. Never localStorage (tokens must not outlive the browser tab / leak across tabs).
 * All token acquisition lives in ./authProvider.ts so SSO can be added without touching callers.
 */

const KEY = 'xdata.auth';

interface Stored {
  token: string;
  expiresAt: number; // epoch ms
}

let memory: Stored | null = null;
const listeners = new Set<() => void>();

function readSession(): Stored | null {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Stored;
    if (typeof parsed.token !== 'string' || typeof parsed.expiresAt !== 'number') return null;
    return parsed;
  } catch {
    return null;
  }
}

export const tokenStore = {
  get(): string | null {
    if (!memory) memory = readSession();
    if (!memory) return null;
    if (Date.now() >= memory.expiresAt) {
      tokenStore.clear();
      return null;
    }
    return memory.token;
  },

  set(token: string, expiresInSeconds: number): void {
    memory = { token, expiresAt: Date.now() + Math.max(0, expiresInSeconds - 30) * 1000 };
    try {
      window.sessionStorage.setItem(KEY, JSON.stringify(memory));
    } catch {
      /* storage blocked: keep in memory only */
    }
    listeners.forEach((l) => l());
  },

  clear(): void {
    const had = memory !== null || readSession() !== null;
    memory = null;
    try {
      window.sessionStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
    if (had) listeners.forEach((l) => l());
  },

  subscribe(fn: () => void): () => void {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};
