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
        <h1>How the AI works</h1>
        <p className="muted">
          What the AI in this product does, what it should not be used for, how people stay in control, and its known limits. {c.purpose}
        </p>
        <p className="tiny muted">Explainability framework followed: {c.xai_principles}</p>
      </header>
      <section className="card"><h2>How each part works and how it is explained</h2>
        <div className="table-wrap">
        <table className="table">
          <thead><tr><th scope="col">Part of the product</th><th scope="col">Kind</th><th scope="col">AI model</th><th scope="col">How you can see why</th></tr></thead>
          <tbody>{c.components.map((x) => (
            <tr key={x.name}><td>{x.name}</td><td>{x.type}</td><td>{x.model ?? '-'}</td><td>{x.explainability ?? '-'}</td></tr>
          ))}</tbody>
        </table>
        </div>
      </section>
      <div className="grid grid-2">
        <section className="card"><h2>Do not use it for</h2>{list(c.not_intended_for)}</section>
        <section className="card"><h2>How people stay in control</h2>{list(c.human_oversight)}</section>
        <section className="card"><h2>Known limitations</h2>{list(c.known_limitations)}</section>
        <section className="card"><h2>Data it uses</h2>{list(c.data.sources)}
          <p className="small">Is your data used to train AI models? <strong>{c.data.customer_data_used_for_training ? 'Yes' : 'No'}</strong></p>
        </section>
      </div>
      <section className="card"><h2>How it is tested</h2>
        <p className="small">Test suite <code>{c.evaluation.suite}</code>: {c.evaluation.gate}.</p>{list(c.evaluation.metrics)}
        <h3>AI instruction (prompt) versions in use</h3>{list(c.prompts.map((p) => `${p.id} v${p.version} (${p.hash})`))}
      </section>
    </div>
  );
}
