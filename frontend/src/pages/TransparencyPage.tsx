import { useQuery } from '@tanstack/react-query';
import { api } from '../api/endpoints';
import { ErrorState, Loading } from '../components/States';

/** AI transparency / model card (explainable-AI disclosure for every user). */
export function TransparencyPage() {
  const q = useQuery({ queryKey: ['ai-transparency'], queryFn: api.aiTransparency });
  if (q.isLoading) return <Loading />;
  if (q.error || !q.data) return <ErrorState error={q.error} />;
  const c = q.data;
  const list = (items: string[]) => <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{items.map((i) => <li key={i}>{i}</li>)}</ul>;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <header>
        <h1>AI transparency</h1>
        <p className="muted">{c.purpose}</p>
        <p className="tiny muted">Explainability framework: {c.xai_principles}</p>
      </header>
      <section className="card"><h2>How each part works and how it is explained</h2>
        <table className="table">
          <thead><tr><th scope="col">Component</th><th scope="col">Type</th><th scope="col">Model</th><th scope="col">Explanation provided</th></tr></thead>
          <tbody>{c.components.map((x) => (
            <tr key={x.name}><td>{x.name}</td><td>{x.type}</td><td>{x.model ?? '-'}</td><td>{x.explainability ?? '-'}</td></tr>
          ))}</tbody>
        </table>
      </section>
      <div className="grid grid-2">
        <section className="card"><h2>Not intended for</h2>{list(c.not_intended_for)}</section>
        <section className="card"><h2>Human oversight</h2>{list(c.human_oversight)}</section>
        <section className="card"><h2>Known limitations</h2>{list(c.known_limitations)}</section>
        <section className="card"><h2>Data</h2>{list(c.data.sources)}
          <p className="small">Customer data used to train models: <strong>{c.data.customer_data_used_for_training ? 'Yes' : 'No'}</strong></p>
        </section>
      </div>
      <section className="card"><h2>Evaluation</h2>
        <p className="small">Suite <code>{c.evaluation.suite}</code>: {c.evaluation.gate}.</p>{list(c.evaluation.metrics)}
        <h3>Prompt versions</h3>{list(c.prompts.map((p) => `${p.id} v${p.version} (${p.hash})`))}
      </section>
    </div>
  );
}
