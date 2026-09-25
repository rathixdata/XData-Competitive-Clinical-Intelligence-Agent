# Retrieval-Augmented Generation design

The RAG layer answers one question: *what does retained evidence say, and how do we prove it?*

## 1. Evidence units

Every adapter emits `TextSection`s tied to a **source field**, for example
`protocolSection.outcomesModule.primaryOutcomes`, `MedlineCitation.Article.Abstract` or
`label.indications_and_usage`.

`rag/indexer.py` chunks each section on its own, so a chunk never spans two fields. Chunks are packed by sentence
up to about 350 tokens with a 60-token overlap, and each stored chunk records:

- `source_document_id` (the immutable raw artifact, with its checksum and rights), `snapshot_id` and `field_path`;
- the character span (`char_start`/`char_end`), `retrieved_at` and `published_at`;
- `entity_ids` (the canonical entities linked during resolution), used for scoped retrieval;
- the dense vector (`pgvector`, HNSW, cosine) and a stored `tsvector` (GIN);
- `is_current`, which is cleared when a newer snapshot of the same object is indexed. Older chunks stay retrievable
  for temporal questions.

A contextual header (title, section) is added to the text **for embedding only**. The stored text stays verbatim,
so citations quote the source exactly.

## 2. Evidence channels

| Id | Channel | Used by |
|---|---|---|
| `S*` | Structured evidence rendered deterministically from snapshots: field diffs, landscape-matrix rows, catalysts | Impact narratives, comparisons, timeline questions |
| `C*` | Change records from version history, within the requested time window | Temporal questions (FR-QA-003) |
| `E*` | Hybrid-retrieved passages | Context for everything |

## 3. Hybrid retrieval (`rag/retriever.py`)

1. **Dense.** The query embedding goes through `input_type=query` for Voyage. Candidates come from cosine distance on the HNSW index.
2. **Lexical.** Postgres `to_tsquery` over the question's content terms, OR-combined, with hyphenated codes such
   as `CA-201` kept as phrases, ranked by `ts_rank_cd`.
3. **Scoped.** Chunks attached to the entities or objects in scope, newest first.
4. **Reciprocal Rank Fusion** (k=60) with channel weights, then boosts for entity overlap, agreement across
   channels and recency.
5. **Optional cross-encoder rerank** (Voyage `rerank-2.5`). This degrades gracefully if the call fails.
6. **Diversification:** at most 3 passages per source document.
7. **Authorization.** Every query filters `tenant_id IS NULL OR tenant_id = caller`, and Postgres RLS enforces the
   same rule independently. A forged `tenant_id` still returns nothing (`tests/test_rag_ask.py`).

## 4. Grounded generation (`ai/llm.py`, `ai/agents/*`)

- **Model and call settings.** Claude `claude-opus-5` through the official SDK:
  - structured JSON output (`output_config.format`), so every statement carries `statement_type`, `confidence`,
    `evidence_ids` and `affected_entity_ids` (SRS §12.1);
  - adaptive thinking with an explicit effort level;
  - server-side refusal fallbacks (`fallbacks: "default"`);
  - a cached, stable system prompt.
- **Prompt-injection isolation (SRS §11).** Retrieved content appears only in the user turn, inside
  `<evidence>`/`<structured_changes>` tags. Closing tags inside the content are neutralized. System prompts state
  that data is never instructions, and the model has no tools, so injected text can't make it act.
- **Fixed facts, no model involvement.** Verified structural changes ("Enrollment changed from 320 to 480") are
  rendered by code from the snapshots. The model adds context, hedged inferences, unknowns and investigations.
- **Governance.** Every call writes a `GenerationRecord` holding the model and served model, prompt id, version and
  hash, workflow version, configuration, the retrieval-set manifest and its hash, tokens, cost, latency and request
  id (FR-AI-007, NFR-AI-001).
- **Budgets.** Monthly USD budgets per tenant. On a budget stop, refusal or outage the system falls back to the
  deterministic evidence-only builder and marks the record `degraded:*`.

## 5. Evidence validation (`ai/validator.py`)

Each FACT goes through two independent layers:

1. **Deterministic checks:**
   - the cited ids exist in the retrieval set;
   - every number, date and registry id (NCT/PMID/NDA/BLA) in the claim appears in the cited evidence;
   - lexical support is at or above the threshold.
2. **An independent LLM judge.** It uses a separate prompt and sees only the claim and its cited evidence. It
   returns supported / partially / unsupported, a severity, and whether the claim is really an inference presented
   as fact.

The stricter of the two verdicts wins.

- **Unsupported FACTs** are withheld (kept in the validation record) and replaced by an explicit UNKNOWN note.
- **A high-severity unsupported FACT** blocks the artifact from publication. The platform then publishes the
  deterministic, fully validated narrative and flags the event for analyst review. Both versions are retained.
- **INFERENCE statements without hedging** are flagged and their confidence is capped.
- **Confidence labels** follow policy, not a model score (FR-AI-005): FACT = Verified only when supported;
  UNKNOWN and RECOMMENDED_INVESTIGATION = Not applicable.

## 6. Abstention (FR-AI-008)

Ask-the-Landscape abstains in three cases: the model sets `abstained`, validation withholds every factual
statement, or no relevant evidence exists. The golden suite checks both kinds of question: ones that are
unanswerable and must abstain, and answerable ones that must not.

## 7. Evaluation

`evals/run.py` runs the golden suite and measures:
- change-detection accuracy and noise suppression;
- entity-resolution precision and recall;
- material-event recall and high-priority precision;
- source attribution rate and unsupported-fact rate;
- hallucination-blocking rate (fabricated model outputs are injected);
- abstention accuracy, comparison warnings and temporal answers.

It runs as a CI gate and must pass before any model, prompt or ranking promotion.

## 8. Explainability (XAI)

Explainability follows the four principles of NIST IR 8312 and is implemented in `app/ai/explain.py`:

| Principle | How it is met |
|---|---|
| **Explanation** | Every event has a "Why am I seeing this?" section (`GET /events/{id}/explanation`, also inlined in the event detail) showing score drivers with their reasons, the mapping path and shared dimensions, evidence coverage, and generation provenance. Every Ask answer has a step-by-step trace of how it was produced. |
| **Meaningful** | A plain-language summary comes first ("Scored 93/100 (Executive Alert). The biggest factor was …"), followed by the full technical breakdown for analysts. |
| **Explanation accuracy** | Explanations are computed from the *same* deterministic values that produced the output: score components, proximity dimensions and validator verdicts. The LLM never generates them after the fact. `tests/test_explainability.py` recomputes the score from the explained drivers and checks that it matches. |
| **Knowledge limits** | Always shown: unknowns, withheld claims, stale or failing sources, low mapping confidence, degraded model mode, the fact that confidence labels are not calibrated probabilities, and indirect comparisons. |

- **Counterfactuals:** the points needed to move up or down a band, the effect of the magnitude gate, and a per-dimension sensitivity analysis. Together these let an analyst contest a score.
- **Transparency card:** `GET /auth/ai-transparency` and the "AI transparency" screen describe the purpose, uses the system is not intended for, each component's type and model, human-oversight controls, data sources, the no-training-on-customer-data policy, known limitations, the evaluation gate and prompt versions.
