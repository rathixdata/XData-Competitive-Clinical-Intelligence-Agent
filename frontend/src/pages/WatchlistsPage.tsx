import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Plus, Trash2, Upload } from 'lucide-react';
import { api } from '../api/endpoints';
import type { Visibility, WatchlistDetail } from '../api/types';
import { PERMS, useAuth } from '../auth/context';
import { Modal } from '../components/Dialog';
import { EntityPicker } from '../components/EntityPicker';
import { EmptyState, ErrorState, InlineError, Loading, QueryView } from '../components/States';
import { useLandscape } from '../state/landscapeContext';
import { fmtDateTime } from '../lib/format';
import { errorMessage, useToast } from '../lib/toastContext';

const ITEM_TYPES = ['company', 'asset', 'mechanism', 'indication', 'trial', 'kol', 'conference', 'regulatory_event'];
const VIS_TEXT: Record<Visibility, string> = { private: 'Private (only me)', team: 'My team', tenant: 'Everyone in the tenant' };

function CreateWatchlist({ onClose }: { onClose: () => void }) {
  const { landscapeId } = useLandscape();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [visibility, setVisibility] = useState<Visibility>('private');
  const m = useMutation({
    mutationFn: () => api.createWatchlist({ name, description: description || undefined, visibility, landscape_id: landscapeId ?? null }),
    onSuccess: (w) => {
      void qc.invalidateQueries({ queryKey: ['watchlists'] });
      navigate(`/watchlists/${w.id}`);
    },
  });
  return (
    <Modal
      open
      onClose={onClose}
      title="New watchlist"
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="wl-form" className="btn btn-primary" disabled={!name.trim() || m.isPending}>
            Create
          </button>
        </>
      }
    >
      <form
        id="wl-form"
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          m.mutate();
        }}
      >
        <InlineError error={m.error} />
        <div className="field">
          <label htmlFor="wl-name">Name</label>
          <input id="wl-name" type="text" required value={name} onChange={(e) => setName(e.target.value)} data-autofocus />
        </div>
        <div className="field">
          <label htmlFor="wl-desc">Description</label>
          <textarea id="wl-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="wl-vis">Sharing</label>
          <select id="wl-vis" value={visibility} onChange={(e) => setVisibility(e.target.value as Visibility)}>
            {Object.entries(VIS_TEXT).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
      </form>
    </Modal>
  );
}

export function WatchlistsPage() {
  const { can } = useAuth();
  const [creating, setCreating] = useState(false);
  const q = useQuery({ queryKey: ['watchlists'], queryFn: api.watchlists });
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Watchlists</h1>
          <p>Track companies, assets, mechanisms and trials. Watched items boost personalised feed ranking and can drive alert policies.</p>
        </div>
        {can(PERMS.watchlistWrite) ? (
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            <Plus size={15} aria-hidden /> New watchlist
          </button>
        ) : null}
      </div>
      <QueryView query={q} isEmpty={(d) => d.length === 0} empty={<div className="card"><EmptyState title="No watchlists yet" /></div>}>
        {(items) => (
          <div className="grid grid-auto">
            {items.map((w) => (
              <article key={w.id} className="card stack-sm">
                <h2 style={{ margin: 0 }}>
                  <Link to={`/watchlists/${w.id}`}>{w.name}</Link>
                </h2>
                {w.description ? <p className="small muted">{w.description}</p> : null}
                <div className="row">
                  <span className="badge badge-neutral">{VIS_TEXT[w.visibility] ?? w.visibility}</span>
                  <span className="badge badge-info">{w.item_count ?? 0} items</span>
                  {w.owned ? <span className="badge badge-success">Owner</span> : <span className="badge badge-neutral">Shared with you</span>}
                </div>
              </article>
            ))}
          </div>
        )}
      </QueryView>
      {creating ? <CreateWatchlist onClose={() => setCreating(false)} /> : null}
    </>
  );
}

function ImportCsv({ wl, onClose }: { wl: WatchlistDetail; onClose: () => void }) {
  const qc = useQueryClient();
  const [csv, setCsv] = useState('item_type,value\n');
  const m = useMutation({
    mutationFn: () => api.importWatchlist(wl.id, csv),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['watchlist', wl.id] }),
  });
  return (
    <Modal
      open
      wide
      onClose={onClose}
      title="Bulk import (CSV)"
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
          <button type="button" className="btn btn-primary" onClick={() => m.mutate()} disabled={m.isPending || csv.trim().split('\n').length < 2}>
            <Upload size={14} aria-hidden /> Import
          </button>
        </>
      }
    >
      <div className="stack">
        <p className="small">
          Columns: <code>item_type,value[,entity_id]</code>. Item types: {ITEM_TYPES.join(', ')}. Names are resolved to canonical entities; unresolved rows are
          still added as free-text items and listed below.
        </p>
        <div className="field">
          <label htmlFor="csv-file">Upload a CSV file</label>
          <input
            id="csv-file"
            type="file"
            accept=".csv,text/csv"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f) setCsv(await f.text());
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="csv-text">Or paste CSV</label>
          <textarea id="csv-text" rows={8} className="mono" value={csv} onChange={(e) => setCsv(e.target.value)} />
        </div>
        <InlineError error={m.error} />
        {m.data ? (
          <div className="banner banner-info" role="status">
            <div>
              <p>
                Added {m.data.added} item(s). {m.data.unresolved.length} row(s) need attention.
              </p>
              {m.data.unresolved.length ? (
                <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
                  {m.data.unresolved.map((u, i) => (
                    <li key={i}>
                      {Object.values(u.row).join(', ')} - {u.error}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}

export function WatchlistDetailPage() {
  const { id = '' } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { notify } = useToast();
  const q = useQuery({ queryKey: ['watchlist', id], queryFn: () => api.watchlist(id) });
  const list = useQuery({ queryKey: ['watchlists'], queryFn: api.watchlists });
  const [importing, setImporting] = useState(false);
  const [freeType, setFreeType] = useState('mechanism');
  const [freeValue, setFreeValue] = useState('');
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['watchlist', id] });
    void qc.invalidateQueries({ queryKey: ['watchlists'] });
  };
  const add = useMutation({
    mutationFn: (item: { item_type: string; entity_id?: string | null; value: string }) => api.addWatchItems(id, [item]),
    onSuccess: (r) => {
      notify(r.added ? 'Item added' : 'Item already on this watchlist');
      refresh();
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  const remove = useMutation({ mutationFn: (itemId: string) => api.removeWatchItem(id, itemId), onSuccess: refresh, onError: (e) => notify(errorMessage(e), 'error') });
  const share = useMutation({
    mutationFn: (visibility: Visibility) => api.patchWatchlist(id, { visibility }),
    onSuccess: () => {
      notify('Sharing updated');
      refresh();
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  const del = useMutation({
    mutationFn: () => api.deleteWatchlist(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['watchlists'] });
      navigate('/watchlists');
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  if (!q.data) return null;
  const wl = q.data;
  const owned = list.data?.find((w) => w.id === id)?.owned ?? false;
  const canEdit = can(PERMS.watchlistWrite) && (owned || can(PERMS.configAdmin));
  return (
    <>
      <nav className="small" aria-label="Breadcrumb" style={{ marginBottom: 8 }}>
        <Link to="/watchlists">
          <ArrowLeft size={13} aria-hidden /> All watchlists
        </Link>
      </nav>
      <div className="page-header">
        <div>
          <h1>{wl.name}</h1>
          <p>{wl.description ?? 'No description'}</p>
        </div>
        {canEdit ? (
          <div className="btn-group">
            <div className="row">
              <label htmlFor="wl-share" className="small strong">
                Sharing
              </label>
              <select id="wl-share" style={{ width: 200 }} value={wl.visibility} onChange={(e) => share.mutate(e.target.value as Visibility)}>
                {Object.entries(VIS_TEXT).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <button type="button" className="btn" onClick={() => setImporting(true)}>
              <Upload size={15} aria-hidden /> Import CSV
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={() => {
                if (window.confirm(`Delete watchlist "${wl.name}"?`)) del.mutate();
              }}
            >
              <Trash2 size={15} aria-hidden /> Delete
            </button>
          </div>
        ) : (
          <span className="badge badge-neutral">{VIS_TEXT[wl.visibility]} - read only</span>
        )}
      </div>
      {canEdit ? (
        <section className="card" aria-labelledby="add-h" style={{ marginBottom: 16 }}>
          <h2 id="add-h">Add items</h2>
          <div className="grid grid-2">
            <EntityPicker
              label="Search entities (company, asset, trial, mechanism, indication...)"
              onSelect={(h) => {
                const t = h.type === 'target' ? 'mechanism' : h.type;
                if (!ITEM_TYPES.includes(t)) {
                  notify(`Entities of type ${h.type} cannot be watched; add it as free text instead`, 'error');
                  return;
                }
                add.mutate({ item_type: t, entity_id: h.id, value: h.name });
              }}
            />
            <form
              className="form-grid"
              onSubmit={(e) => {
                e.preventDefault();
                if (freeValue.trim()) {
                  add.mutate({ item_type: freeType, value: freeValue.trim(), entity_id: null });
                  setFreeValue('');
                }
              }}
            >
              <div className="field">
                <label htmlFor="free-type">Type</label>
                <select id="free-type" value={freeType} onChange={(e) => setFreeType(e.target.value)}>
                  {ITEM_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t.replace(/_/g, ' ')}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="free-val">Free-text value</label>
                <input id="free-val" type="text" value={freeValue} onChange={(e) => setFreeValue(e.target.value)} />
              </div>
              <div className="field">
                <button type="submit" className="btn" disabled={!freeValue.trim()}>
                  Add
                </button>
              </div>
            </form>
          </div>
        </section>
      ) : null}
      <section className="card" aria-labelledby="items-h">
        <h2 id="items-h">Items ({wl.items.length})</h2>
        {wl.items.length === 0 ? (
          <EmptyState title="No items yet" />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Type</th>
                  <th scope="col">Value</th>
                  <th scope="col">Resolution</th>
                  <th scope="col">Added</th>
                  {canEdit ? <th scope="col">Actions</th> : null}
                </tr>
              </thead>
              <tbody>
                {wl.items.map((it) => (
                  <tr key={it.id}>
                    <td>{it.item_type.replace(/_/g, ' ')}</td>
                    <td>{it.item_type === 'asset' && it.entity_id ? <Link to={`/assets/${it.entity_id}`}>{it.value || it.entity_id}</Link> : it.value || it.entity_id}</td>
                    <td>{it.entity_id ? <span className="badge badge-success">Linked to entity</span> : <span className="badge badge-warning">Free text (unresolved)</span>}</td>
                    <td className="small">{fmtDateTime(it.created_at)}</td>
                    {canEdit ? (
                      <td>
                        <button type="button" className="btn btn-sm btn-ghost" onClick={() => remove.mutate(it.id)} aria-label={`Remove ${it.value}`}>
                          <Trash2 size={14} aria-hidden />
                        </button>
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {importing ? <ImportCsv wl={wl} onClose={() => setImporting(false)} /> : null}
    </>
  );
}
