import type { ReactNode } from 'react';
import { useAuth } from './context';
import { EmptyState } from '../components/States';

/** Hides a screen the user lacks permission for (the server enforces regardless). */
export function RequirePerm({ perm, children }: { perm: string; children: ReactNode }) {
  const { can } = useAuth();
  if (!can(perm)) {
    return (
      <div className="card">
        <EmptyState title="You do not have access to this screen">This requires the {perm} permission. Ask your tenant administrator if you need it.</EmptyState>
      </div>
    );
  }
  return <>{children}</>;
}
