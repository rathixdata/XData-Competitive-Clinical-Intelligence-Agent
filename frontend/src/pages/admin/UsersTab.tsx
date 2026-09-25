import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { api } from '../../api/endpoints';
import type { User } from '../../api/types';
import { useAuth } from '../../auth/context';
import { StatusBadge } from '../../components/Badges';
import { Modal } from '../../components/Dialog';
import { InlineError, QueryView } from '../../components/States';
import { fmtDateTime } from '../../lib/format';
import { useToast } from '../../lib/toastContext';

function RolePicker({ roles, value, onChange }: { roles: string[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <fieldset>
      <legend>Roles</legend>
      <div className="row">
        {roles
          .filter((r) => r !== 'platform_admin')
          .map((r) => (
            <label key={r} className="checkbox">
              <input type="checkbox" checked={value.includes(r)} onChange={(e) => onChange(e.target.checked ? [...value, r] : value.filter((x) => x !== r))} />
              {r.replace(/_/g, ' ')}
            </label>
          ))}
      </div>
    </fieldset>
  );
}

function UserEditor({ user, roles, onClose }: { user: User | null; roles: string[]; onClose: () => void }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const [form, setForm] = useState({
    email: user?.email ?? '',
    display_name: user?.display_name ?? '',
    team: user?.team ?? '',
    password: '',
    roles: user?.roles ?? ['viewer'],
    is_active: user?.is_active ?? true,
  });
  const m = useMutation({
    mutationFn: () =>
      user
        ? api.patchUser(user.id, { roles: form.roles, team: form.team || undefined, is_active: form.is_active, display_name: form.display_name })
        : api.createUser({ email: form.email, display_name: form.display_name, roles: form.roles, team: form.team || undefined, password: form.password || undefined }),
    onSuccess: () => {
      notify(user ? 'User updated' : 'User created');
      void qc.invalidateQueries({ queryKey: ['admin-users'] });
      onClose();
    },
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={user ? `Edit ${user.email}` : 'Invite user'}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="user-form" className="btn btn-primary" disabled={m.isPending || form.roles.length === 0}>
            Save
          </button>
        </>
      }
    >
      <form
        id="user-form"
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          m.mutate();
        }}
      >
        <InlineError error={m.error} />
        <div className="form-grid">
          <div className="field">
            <label htmlFor="u-email">Email</label>
            <input id="u-email" type="email" required disabled={Boolean(user)} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="u-name">Display name</label>
            <input id="u-name" type="text" required value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="u-team">Team</label>
            <input id="u-team" type="text" value={form.team} onChange={(e) => setForm({ ...form, team: e.target.value })} />
          </div>
          {!user ? (
            <div className="field">
              <label htmlFor="u-pass">Initial password (optional, min 12)</label>
              <input id="u-pass" type="password" minLength={12} autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
              <span className="hint">Leave blank for SSO-only users.</span>
            </div>
          ) : (
            <label className="checkbox">
              <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Active
            </label>
          )}
        </div>
        <RolePicker roles={roles} value={form.roles} onChange={(r) => setForm({ ...form, roles: r })} />
      </form>
    </Modal>
  );
}

export function UsersTab() {
  const { me } = useAuth();
  const users = useQuery({ queryKey: ['admin-users'], queryFn: api.users });
  const roles = useQuery({ queryKey: ['admin-roles'], queryFn: api.roles });
  const [editing, setEditing] = useState<User | 'new' | null>(null);
  const roleNames = Object.keys(roles.data ?? {}).length ? Object.keys(roles.data ?? {}) : (me?.available_roles ?? []);
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div>
        <button type="button" className="btn btn-primary" onClick={() => setEditing('new')}>
          <Plus size={15} aria-hidden /> Invite user
        </button>
      </div>
      <QueryView query={users}>
        {(list) => (
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Users</caption>
              <thead>
                <tr>
                  <th scope="col">User</th>
                  <th scope="col">Roles</th>
                  <th scope="col">Team</th>
                  <th scope="col">State</th>
                  <th scope="col">Last login</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {list.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <strong>{u.display_name}</strong>
                      <div className="small muted">{u.email}</div>
                    </td>
                    <td>
                      {u.roles.map((r) => (
                        <span key={r} className="badge badge-neutral" style={{ marginRight: 4 }}>
                          {r.replace(/_/g, ' ')}
                        </span>
                      ))}
                    </td>
                    <td>{u.team ?? '-'}</td>
                    <td>
                      <StatusBadge status={u.is_active ? 'active' : 'inactive'} />
                    </td>
                    <td className="nowrap">{fmtDateTime(u.last_login_at)}</td>
                    <td>
                      <button type="button" className="btn btn-sm" onClick={() => setEditing(u)} aria-label={`Edit ${u.email}`}>
                        Edit
                      </button>
                      {u.id === me?.user.id ? <span className="tiny muted"> (you)</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </QueryView>
      <section className="card" aria-labelledby="roles-h">
        <h2 id="roles-h">Role permissions</h2>
        <QueryView query={roles}>
          {(r) => {
            const perms = Array.from(new Set(Object.values(r).flat())).sort();
            return (
              <div className="table-wrap">
                <table className="table">
                  <caption className="sr-only">Permissions granted per role</caption>
                  <thead>
                    <tr>
                      <th scope="col">Permission</th>
                      {Object.keys(r).map((role) => (
                        <th key={role} scope="col" style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)', height: 130, whiteSpace: 'nowrap' }}>
                          {role.replace(/_/g, ' ')}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {perms.map((p) => (
                      <tr key={p}>
                        <th scope="row" className="mono">
                          {p}
                        </th>
                        {Object.entries(r).map(([role, ps]) => (
                          <td key={role} style={{ textAlign: 'center' }}>
                            {ps.includes(p) ? (
                              <span aria-label="granted" title="granted">
                                Yes
                              </span>
                            ) : (
                              <span className="muted" aria-label="not granted">
                                -
                              </span>
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          }}
        </QueryView>
      </section>
      {editing ? <UserEditor user={editing === 'new' ? null : editing} roles={roleNames} onClose={() => setEditing(null)} /> : null}
    </div>
  );
}
