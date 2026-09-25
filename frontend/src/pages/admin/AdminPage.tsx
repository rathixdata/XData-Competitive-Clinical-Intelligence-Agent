import type { ReactNode } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { PERMS, useAuth } from '../../auth/context';
import { Tabs } from '../../components/Tabs';
import { EmptyState } from '../../components/States';
import { UsersTab } from './UsersTab';
import { ConnectorsTab } from './ConnectorsTab';
import { ProximityTab } from './ProximityTab';
import { ModelsTab, SettingsTab, UsageTab } from './GovernanceTabs';
import { AuditTab } from './AuditTab';
import { KpisTab, TuningTab } from './TuningTabs';

interface TabSpec {
  id: string;
  label: string;
  perms: string[];
  render: () => ReactNode;
}

const TABS: TabSpec[] = [
  { id: 'connectors', label: 'Connectors', perms: [PERMS.sourceRead], render: () => <ConnectorsTab /> },
  { id: 'users', label: 'Users & roles', perms: [PERMS.userAdmin], render: () => <UsersTab /> },
  { id: 'proximity', label: 'Proximity rules', perms: [PERMS.configAdmin], render: () => <ProximityTab /> },
  { id: 'models', label: 'Models & workflows', perms: [PERMS.configAdmin], render: () => <ModelsTab /> },
  { id: 'settings', label: 'Settings', perms: [PERMS.configAdmin], render: () => <SettingsTab /> },
  { id: 'usage', label: 'Usage', perms: [PERMS.configAdmin], render: () => <UsageTab /> },
  { id: 'audit', label: 'Audit log', perms: [PERMS.auditRead], render: () => <AuditTab /> },
  { id: 'tuning', label: 'Feedback tuning', perms: [PERMS.trainingCurate], render: () => <TuningTab /> },
  { id: 'kpis', label: 'KPIs', perms: ['report:read'], render: () => <KpisTab /> },
];

export function AdminPage() {
  const { tab } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
  const visible = TABS.filter((t) => t.perms.some(can));
  if (visible.length === 0) {
    return (
      <div className="card">
        <EmptyState title="You do not have access to administration" />
      </div>
    );
  }
  const active = visible.find((t) => t.id === tab);
  if (!active) return <Navigate to={`/admin/${visible[0].id}`} replace />;
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Administration</h1>
          <p>Sections are shown according to your permissions; the server enforces every action.</p>
        </div>
      </div>
      <Tabs label="Administration sections" active={active.id} onChange={(id) => navigate(`/admin/${id}`)} tabs={visible.map((t) => ({ id: t.id, label: t.label }))} />
      <div role="tabpanel" id={`panel-${active.id}`} aria-labelledby={`tab-${active.id}`}>
        {active.render()}
      </div>
    </>
  );
}
