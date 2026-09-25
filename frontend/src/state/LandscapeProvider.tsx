import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/endpoints';
import { LandscapeContext } from './landscapeContext';

const KEY = 'xdata.landscape';

function readStored(): string | undefined {
  try {
    return window.localStorage.getItem(KEY) ?? undefined;
  } catch {
    return undefined;
  }
}

/** Selected landscape (persisted per browser; it is a UI preference, not a credential). */
export function LandscapeProvider({ children }: { children: ReactNode }) {
  const q = useQuery({ queryKey: ['landscapes'], queryFn: api.landscapes, staleTime: 60_000 });
  const [stored, setStored] = useState<string | undefined>(readStored);

  const setLandscapeId = useCallback((id: string) => {
    setStored(id);
    try {
      window.localStorage.setItem(KEY, id);
    } catch {
      /* ignore */
    }
  }, []);

  const value = useMemo(() => {
    const landscapes = q.data ?? [];
    const landscape = landscapes.find((l) => l.id === stored) ?? landscapes[0];
    return { landscapes, landscapeId: landscape?.id, landscape, setLandscapeId, loading: q.isLoading };
  }, [q.data, q.isLoading, stored, setLandscapeId]);

  return <LandscapeContext.Provider value={value}>{children}</LandscapeContext.Provider>;
}
