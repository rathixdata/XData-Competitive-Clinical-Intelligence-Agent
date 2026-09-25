import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, X } from 'lucide-react';
import { api } from '../api/endpoints';
import type { EntityLink, EntitySearchHit } from '../api/types';
import { PERMS, useAuth } from '../auth/context';
import { EntityPicker } from '../components/EntityPicker';
import { EmptyState, InlineError, QueryView } from '../components/States';
import { Tabs } from '../components/Tabs';
import { fmtDateTime, shortId } from '../lib/format';
import { errorMessage, useToast } from '../lib/toastContext';

const TYPES = ['company', 'asset', 'target', 'mechanism', 'indication', 'biomarker', 'endpoint', 'modality', 'line_of_therapy', 'conference', 'kol'];
const ALIAS_TYPES = ['synonym', 'dev_code', 'generic', 'brand', 'legacy', 'abbreviation', 'spelling'];

function ReviewItem({ link }: { link: EntityLink }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const [reason, setReason] = useState('');
  const [target, setTarget] = useState<EntitySearchHit | null>(null);
  const decide = useMutation({
    mutationFn: (decision: 'approve' | 'reject') => api.decideReview(link.id, { decision, entity_id: target?.id ?? null, reason: reason || undefined }),
    onSuccess: (_r, decision) => {
      notify(decision === 'approve' ? `Approved "${link.mention}"` : `Rejected "${link.mention}"`);
      void qc.invalidateQueries({ queryKey: ['entity-review'] });
    },
    onError: (e) => notify(errorMessage(e), 'error'),
  });
  const pending = link.status === 'pending_review';
  return (
    <li className="stack-sm">
      <div className="row-between" style={{ alignItems: 'flex-start' }}>
        <div className="stack-sm" style={{ gap: 2 }}>
          <div className="row">
            <strong>&ldquo;{link.mention}&rdquo;</strong>
            <span className="badge badge-neutral">{link.entity_type}</span>
            <span className="badge badge-info">Confidence {(link.confidence * 100).toFixed(0)}%</span>
            <span className="badge badge-neutral">{link.method.replace(/_/g, ' ')}</span>
            {!pending ? <span className={`badge ${link.status === 'approved' ? 'badge-success' : 'badge-danger'}`}>{link.status}</span> : null}
          </div>
          {link.context_label ? <span className="small muted">Seen in: {link.context_label}</span> : null}
          <span className="small">
            Proposed match:{' '}
            {link.candidates?.length
              ? link.candidates.map((c) => `${c.alias ?? c.name ?? shortId(c.entity_id)} (${((c.score ?? 0) * 100).toFixed(0)}%)`).join('; ')
              : link.entity_id
                ? shortId(link.entity_id)
                : 'none (unresolved)'}
          </span>
          {link.reviewed_by ? (
            <span className="tiny muted">
              Reviewed by {shortId(link.reviewed_by)} {link.review_reason ? `- ${link.review_reason}` : ''} {fmtDateTime(link.updated_at)}
            </span>
          ) : null}
        </div>
      </div>
      {pending ? (
        <div className="form-grid">
          <EntityPicker label="Different target (optional)" type={link.entity_type} onSelect={setTarget} />
          <div className="field">
            <label htmlFor={`rr-${link.id}`}>Reason</label>
            <input id={`rr-${link.id}`} type="text" value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <div className="btn-group">
            <button type="button" className="btn btn-primary btn-sm" onClick={() => decide.mutate('approve')} disabled={decide.isPending || (!link.entity_id && !target)}>
              <Check size={14} aria-hidden /> Approve{target ? ` as ${target.name}` : ''}
            </button>
            <button type="button" className="btn btn-sm" onClick={() => decide.mutate('reject')} disabled={decide.isPending}>
              <X size={14} aria-hidden /> Reject
            </button>
          </div>
        </div>
      ) : null}
    </li>
  );
}

function Queue() {
  const [status, setStatus] = useState('pending_review');
  const [type, setType] = useState('');
  const [offset, setOffset] = useState(0);
  const q = useQuery({ queryKey: ['entity-review', status, type, offset], queryFn: () => api.reviewQueue({ status, entity_type: type || undefined, offset, limit: 25 }) });
  return (
    <div className="stack">
      <div className="form-grid">
        <div className="field">
          <label htmlFor="rq-status">Status</label>
          <select
            id="rq-status"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            <option value="pending_review">Pending review</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="rq-type">Entity type</label>
          <select
            id="rq-type"
            value={type}
            onChange={(e) => {
              setType(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All types</option>
            {TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>
      </div>
      <QueryView query={q} isEmpty={(d) => d.items.length === 0} empty={<div className="card"><EmptyState title="Queue is empty" /></div>}>
        {(d) => (
          <>
            <ul className="list-plain card">
              {d.items.map((l) => (
                <ReviewItem key={l.id} link={l} />
              ))}
            </ul>
            <div className="row-between">
              <span className="small muted">{d.total} total</span>
              <div className="btn-group">
                <button type="button" className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>
                  Previous
                </button>
                <button type="button" className="btn btn-sm" disabled={d.next_offset === null} onClick={() => setOffset(d.next_offset ?? 0)}>
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </QueryView>
    </div>
  );
}

function AliasForm() {
  const { notify } = useToast();
  const [type, setType] = useState('asset');
  const [entity, setEntity] = useState<EntitySearchHit | null>(null);
  const [alias, setAlias] = useState('');
  const [aliasType, setAliasType] = useState('synonym');
  const [reason, setReason] = useState('');
  const m = useMutation({
    mutationFn: () => api.addAlias(type, entity?.id as string, { alias, alias_type: aliasType, reason: reason || undefined }),
    onSuccess: () => {
      notify(`Alias "${alias}" added to ${entity?.name}`);
      setAlias('');
      setReason('');
    },
  });
  return (
    <form
      className="stack card"
      onSubmit={(e) => {
        e.preventDefault();
        m.mutate();
      }}
    >
      <h2>Add alias</h2>
      <InlineError error={m.error} />
      <div className="form-grid">
        <div className="field">
          <label htmlFor="al-type">Entity type</label>
          <select id="al-type" value={type} onChange={(e) => (setType(e.target.value), setEntity(null))}>
            {TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>
        <EntityPicker label="Entity" type={type} onSelect={setEntity} />
        <div className="field">
          <span className="label">Selected</span>
          <span>{entity ? entity.name : <span className="muted">none</span>}</span>
        </div>
        <div className="field">
          <label htmlFor="al-alias">Alias</label>
          <input id="al-alias" type="text" required value={alias} onChange={(e) => setAlias(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="al-atype">Alias type</label>
          <select id="al-atype" value={aliasType} onChange={(e) => setAliasType(e.target.value)}>
            {ALIAS_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="al-reason">Reason</label>
          <input id="al-reason" type="text" value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
      </div>
      <div>
        <button type="submit" className="btn btn-primary" disabled={!entity || !alias.trim() || m.isPending}>
          Add alias
        </button>
      </div>
    </form>
  );
}

function MergeForm() {
  const { notify } = useToast();
  const [type, setType] = useState('asset');
  const [src, setSrc] = useState<EntitySearchHit | null>(null);
  const [tgt, setTgt] = useState<EntitySearchHit | null>(null);
  const [reason, setReason] = useState('');
  const m = useMutation({
    mutationFn: () => api.mergeEntities({ entity_type: type, source_id: src?.id as string, target_id: tgt?.id as string, reason }),
    onSuccess: () => {
      notify(`Merged ${src?.name} into ${tgt?.name}`);
      setSrc(null);
      setTgt(null);
      setReason('');
    },
  });
  return (
    <form
      className="stack card"
      onSubmit={(e) => {
        e.preventDefault();
        if (window.confirm(`Merge "${src?.name}" into "${tgt?.name}"? Aliases, links and relationships move to the target.`)) m.mutate();
      }}
    >
      <h2>Merge duplicate entities</h2>
      <p className="small muted">Public (shared) entities can only be merged by platform administrators; propose corrections via the review queue instead.</p>
      <InlineError error={m.error} />
      <div className="form-grid">
        <div className="field">
          <label htmlFor="mg-type">Entity type</label>
          <select id="mg-type" value={type} onChange={(e) => (setType(e.target.value), setSrc(null), setTgt(null))}>
            {TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>
        <EntityPicker label="Duplicate (source)" type={type} onSelect={setSrc} />
        <EntityPicker label="Keep (target)" type={type} onSelect={setTgt} />
      </div>
      <p className="small">
        {src ? `Merge "${src.name}"${src.private ? '' : ' (public)'}` : 'Pick a source'} {tgt ? `into "${tgt.name}"` : ''}
      </p>
      <div className="field">
        <label htmlFor="mg-reason">Reason (required)</label>
        <input id="mg-reason" type="text" required value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      <div>
        <button type="submit" className="btn btn-danger" disabled={!src || !tgt || src.id === tgt.id || !reason.trim() || m.isPending}>
          Merge
        </button>
      </div>
    </form>
  );
}

function SplitForm() {
  const { notify } = useToast();
  const [type, setType] = useState('asset');
  const [entity, setEntity] = useState<EntitySearchHit | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [newName, setNewName] = useState('');
  const [reason, setReason] = useState('');
  const detail = useQuery({ queryKey: ['entity', type, entity?.id], queryFn: () => api.entity(type, entity?.id as string), enabled: Boolean(entity) });
  const m = useMutation({
    mutationFn: () => api.splitEntity({ entity_type: type, entity_id: entity?.id as string, new_name: newName, alias_ids: selected, reason }),
    onSuccess: (r) => {
      notify(`Split created a new entity; ${r.aliases_moved} alias(es) moved`);
      setSelected([]);
      setNewName('');
      setReason('');
      void detail.refetch();
    },
  });
  return (
    <form
      className="stack card"
      onSubmit={(e) => {
        e.preventDefault();
        m.mutate();
      }}
    >
      <h2>Split an entity</h2>
      <p className="small muted">Move selected aliases to a new entity when two different things were conflated.</p>
      <InlineError error={m.error} />
      <div className="form-grid">
        <div className="field">
          <label htmlFor="sp-type">Entity type</label>
          <select id="sp-type" value={type} onChange={(e) => (setType(e.target.value), setEntity(null), setSelected([]))}>
            {TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>
        <EntityPicker
          label="Entity to split"
          type={type}
          onSelect={(h) => {
            setEntity(h);
            setSelected([]);
          }}
        />
      </div>
      {entity ? (
        <fieldset>
          <legend>Aliases of {entity.name} to move</legend>
          {detail.isLoading ? <span className="small muted">Loading aliases...</span> : null}
          <div className="row">
            {(detail.data?.aliases ?? []).map((a) => (
              <label key={a.id} className="checkbox">
                <input type="checkbox" checked={selected.includes(a.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, a.id] : selected.filter((x) => x !== a.id))} />
                {a.alias} <span className="tiny muted">({a.alias_type})</span>
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}
      <div className="form-grid">
        <div className="field">
          <label htmlFor="sp-name">New entity name</label>
          <input id="sp-name" type="text" required value={newName} onChange={(e) => setNewName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="sp-reason">Reason (required)</label>
          <input id="sp-reason" type="text" required value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
      </div>
      <div>
        <button type="submit" className="btn btn-primary" disabled={!entity || selected.length === 0 || !newName.trim() || !reason.trim() || m.isPending}>
          Split
        </button>
      </div>
    </form>
  );
}

export function EntityReviewPage() {
  const { can } = useAuth();
  const [tab, setTab] = useState('queue');
  if (!can(PERMS.entityCurate)) {
    return (
      <div className="card">
        <EmptyState title="Entity curation requires the entity:curate permission" />
      </div>
    );
  }
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Entity review</h1>
          <p>Approve or reject machine-proposed entity matches. Decisions are audited and reused by the resolver.</p>
        </div>
      </div>
      <Tabs
        label="Curation sections"
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'queue', label: 'Review queue' },
          { id: 'alias', label: 'Aliases' },
          { id: 'merge', label: 'Merge / split' },
        ]}
      />
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === 'queue' ? <Queue /> : null}
        {tab === 'alias' ? <AliasForm /> : null}
        {tab === 'merge' ? (
          <div className="stack" style={{ gap: 16 }}>
            <MergeForm />
            <SplitForm />
          </div>
        ) : null}
      </div>
    </>
  );
}
