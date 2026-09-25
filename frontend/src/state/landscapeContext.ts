import { createContext, useContext } from 'react';
import type { Landscape } from '../api/types';

export interface LandscapeState {
  landscapes: Landscape[];
  landscapeId: string | undefined;
  landscape: Landscape | undefined;
  setLandscapeId: (id: string) => void;
  loading: boolean;
}

export const LandscapeContext = createContext<LandscapeState>({
  landscapes: [],
  landscapeId: undefined,
  landscape: undefined,
  setLandscapeId: () => undefined,
  loading: false,
});

export function useLandscape(): LandscapeState {
  return useContext(LandscapeContext);
}
