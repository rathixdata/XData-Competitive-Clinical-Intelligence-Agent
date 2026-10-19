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
  description: string;
  perms: string[];
  render: () => ReactNode;
}

const TABS: TabSpec[] = [
  {
    id: 'connectors',
    label: 'Data sources',
    description: 'The public sources we check for changes (trial registries, PubMed, FDA, SEC...), when each was last updated, and whether any are failing.',
    perms: [PERMS.sourceRead],
    render: () => <ConnectorsTab />,
  },
  {
    id: 'users',
    label: 'Users & access',
    description: 'Invite colleagues and choose what each person is allowed to see and do.',
    perms: [PERMS.userAdmin],
    render: () => <UsersTab />,
  },
  {
    id: 'proximity',
    label: 'Drug similarity rules',
    description: 'Rules that decide how "close" a competitor is to your drug (shared target, disease, patients...). This drives the "How close to your drug" percentage.',
    perms: [PERMS.configAdmin],
    render: () => <ProximityTab />,
  },
  {
    id: 'models',
    label: 'AI models',
    description: 'Which AI models and instruction versions are used, and how often they ran.',
    perms: [PERMS.configAdmin],
    render: () => <ModelsTab />,
  },
  {
    id: 'settings',
    label: 'Budget & data retention',
    description: 'Monthly AI spending limit and how long different kinds of data are kept.',
    perms: [PERMS.configAdmin],
    render: () => <SettingsTab />,
  },
  {
    id: 'usage',
    label: 'AI usage & cost',
    description: 'How much AI processing was used and what it cost, against your budget.',
    perms: [PERMS.configAdmin],
    render: () => <UsageTab />,
  },
  {
    id: 'audit',
    label: 'Activity log',
    description: 'A tamper-proof record of who did what and when (reviews, edits, approvals, settings changes).',
    perms: [PERMS.auditRead],
    render: () => <AuditTab />,
  },
  {
    id: 'tuning',
    label: 'Improve from feedback',
    description: 'Use analysts\' "useful / not useful" feedback to suggest better priority thresholds. Nothing changes automatically.',
    perms: [PERMS.trainingCurate],
    render: () => <TuningTab />,
  },
  {
    id: 'kpis',
    label: 'Quality metrics',
    description: 'How well the system is performing: evidence coverage, alert precision, speed from source to alert.',
    perms: ['report:read'],
    render: () => <KpisTab />,
  },
];

export function AdminPage() {
  const { tab } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
  const visible = TABS.filter((t) => t.perms.some(can));
  if (visible.length === 0) {
    return (
      <div className="card">
        <EmptyState title="You don't have access to settings">Ask an administrator if you need to manage data sources, users or rules.</EmptyState>
      </div>
    );
  }
  const active = visible.find((t) => t.id === tab);
  if (!active) return <Navigate to={`/admin/${visible[0].id}`} replace />;
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Settings &amp; data sources</h1>
          <p>Check that data sources are up to date and manage users, rules and AI settings. You only see the sections your role allows.</p>
        </div>
      </div>
      <Tabs label="Settings sections" active={active.id} onChange={(id) => navigate(`/admin/${id}`)} tabs={visible.map((t) => ({ id: t.id, label: t.label }))} />
      <p className="small muted tab-intro">{active.description}</p>
      <div role="tabpanel" id={`panel-${active.id}`} aria-labelledby={`tab-${active.id}`}>
        {active.render()}
      </div>
    </>
  );
}
