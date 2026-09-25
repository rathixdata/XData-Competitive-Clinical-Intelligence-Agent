import { useQuery } from '@tanstack/react-query';
import { ExternalLink, ShieldCheck } from 'lucide-react';
import { api } from '../api/endpoints';
import type { EvidenceLink, SourceRights } from '../api/types';
import { fmtDateTime, humanize } from '../lib/format';
import { Drawer } from './Dialog';
import { ErrorState, Loading } from './States';
import { useAuth, PERMS } from '../auth/context';

export function RightsBlock({ rights }: { rights: SourceRights | null | undefined }) {
  if (!rights || Object.keys(rights).length === 0) {
    return <p className="small muted">No rights metadata recorded for this source; check the source terms before redistribution.</p>;
  }
  return (
    <dl className="kv small">
      {rights.license ? (
        <>
          <dt>License</dt>
          <dd>{rights.license}</dd>
        </>
      ) : null}
      {rights.attribution ? (
        <>
          <dt>Attribution</dt>
          <dd>{rights.attribution}</dd>
        </>
      ) : null}
      {rights.redistribution ? (
        <>
          <dt>Redistribution</dt>
          <dd>{rights.redistribution}</dd>
        </>
      ) : null}
      {rights.terms_url ? (
        <>
          <dt>Terms</dt>
          <dd>
            <a href={rights.terms_url} target="_blank" rel="noreferrer noopener">
              Source terms <ExternalLink size={11} aria-hidden />
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          </dd>
        </>
      ) : null}
    </dl>
  );
}

function ChunkContext({ chunkId }: { chunkId: string }) {
  const { can } = useAuth();
  const q = useQuery({ queryKey: ['chunk', chunkId], queryFn: () => api.evidenceContext(chunkId, 1), enabled: can(PERMS.sourceRead) });
  if (!can(PERMS.sourceRead)) return <p className="small muted">Source context requires the source:read permission.</p>;
  if (q.isLoading) return <Loading label="Loading source context" />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  if (!q.data) return null;
  const d = q.data;
  return (
    <section aria-label="Source context" className="stack-sm">
      <h3>Source context</h3>
      <p className="small muted">Surrounding passages from the retained source document. The cited passage is highlighted.</p>
      <ol className="list-plain">
        {d.context.map((c) => (
          <li key={c.chunk_id}>
            <div className="tiny muted">
              Passage {c.index} {c.section ? `- ${humanize(c.section)}` : ''}
              {c.is_target ? <strong> (cited)</strong> : null}
            </div>
            {c.is_target ? (
              <mark style={{ display: 'block', background: '#fff4c2', padding: '6px 8px', borderRadius: 4 }}>{c.text}</mark>
            ) : (
              <p className="small" style={{ margin: 0 }}>
                {c.text}
              </p>
            )}
          </li>
        ))}
      </ol>
      <dl className="kv small">
        <dt>Document</dt>
        <dd>{d.document.title ?? d.chunk.title ?? d.document.uri ?? '-'}</dd>
        <dt>Retrieved</dt>
        <dd>{fmtDateTime(d.document.retrieved_at)}</dd>
        {d.document.source_last_updated ? (
          <>
            <dt>Source last updated</dt>
            <dd>{d.document.source_last_updated}</dd>
          </>
        ) : null}
        {d.document.checksum ? (
          <>
            <dt>Checksum</dt>
            <dd className="mono truncate" title={d.document.checksum}>
              {d.document.checksum.slice(0, 16)}...
            </dd>
          </>
        ) : null}
      </dl>
      <h4>Rights</h4>
      <RightsBlock rights={d.document.rights ?? d.chunk.meta?.rights} />
    </section>
  );
}

/** Evidence drawer: structured evidence (snapshot/field/uri) or passage evidence with surrounding context. */
export function EvidenceDrawer({ link, onClose }: { link: EvidenceLink | null; onClose: () => void }) {
  return (
    <Drawer open={Boolean(link)} onClose={onClose} title={link ? `Evidence ${link.evidence_id}` : 'Evidence'}>
      {link ? (
        <div className="stack">
          <div className="row">
            <span className="badge badge-sourced">
              <ShieldCheck size={12} aria-hidden /> Source evidence
            </span>
            <span className="badge badge-neutral">{humanize(link.kind)}</span>
            {link.is_current === false ? <span className="badge badge-warning">Superseded snapshot</span> : null}
          </div>
          {link.title ? <h3 style={{ margin: 0 }}>{link.title}</h3> : null}
          {link.excerpt ? (
            <blockquote style={{ margin: 0, padding: '8px 12px', borderLeft: '4px solid var(--fact-bd)', background: 'var(--fact-bg)' }}>
              {link.excerpt}
            </blockquote>
          ) : null}
          <dl className="kv small">
            <dt>Source</dt>
            <dd>{link.source_type ?? link.source ?? '-'}</dd>
            {link.field_path ? (
              <>
                <dt>Field</dt>
                <dd className="mono">{link.field_path}</dd>
              </>
            ) : null}
            {link.section ? (
              <>
                <dt>Section</dt>
                <dd>{humanize(link.section)}</dd>
              </>
            ) : null}
            {link.snapshot_id ? (
              <>
                <dt>Snapshot</dt>
                <dd className="mono">{link.snapshot_id}</dd>
              </>
            ) : null}
            <dt>Retrieved</dt>
            <dd>{fmtDateTime(link.retrieved_at)}</dd>
            {link.published_at ? (
              <>
                <dt>Published</dt>
                <dd>{fmtDateTime(link.published_at)}</dd>
              </>
            ) : null}
            {link.uri ? (
              <>
                <dt>Source link</dt>
                <dd>
                  <a href={link.uri} target="_blank" rel="noreferrer noopener">
                    {link.uri} <ExternalLink size={11} aria-hidden />
                    <span className="sr-only"> (opens in a new tab)</span>
                  </a>
                </dd>
              </>
            ) : null}
          </dl>
          {link.chunk_id ? <ChunkContext chunkId={link.chunk_id} /> : (
            <section className="stack-sm">
              <h4>Rights</h4>
              <RightsBlock rights={link.rights} />
            </section>
          )}
        </div>
      ) : null}
    </Drawer>
  );
}
