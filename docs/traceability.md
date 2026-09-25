# SRS v1.0 requirement traceability

Status: **Done** = implemented and verified by the named test(s). **Partial** = implemented, with the stated gap.
Test paths are relative to `backend/tests/` unless noted. "Golden" = `evals/run.py` golden suite.

## 7.1 Landscape configuration
| ID | Pri | Implementation | Verification | Status |
|---|---|---|---|---|
| FR-LND-001 | Must | `services/landscapes.py`, `api/v1/landscapes.py`: create, edit, archive/restore, export; every change audited | `test_api_workflows::test_us001_landscape_configuration` | Done |
| FR-LND-002 | Must | Watchlists: CRUD, items, CSV bulk import with resolution, owner, private/team/tenant sharing, `alert_policy_id`; policies can target a watchlist | `test_watchlist_bulk_import_and_sharing` | Done |
| FR-LND-003 | Must | Tenant-configurable profile fields (`profile_field_definitions`, `PUT /profile-fields`), validated; versioned profiles (`asset_profile_versions`) | `test_api_workflows` (profile via seed), `/assets/{id}/profile/versions` | Done |
| FR-LND-004 | Must | `proximity_rules` with weighted dimensions (target, indication, line, biomarker, modality, geography); `/test` against sample assets; activation refused until tested | `test_proximity_rule_requires_test_before_activation`, `test_materiality::test_proximity_*` | Done |
| FR-LND-005 | Should | `landscape_templates`; only whitelisted non-customer keys are copied | `test_us001_landscape_configuration` (asserts no `nct_ids` copied) | Done |

## 7.2 Sources and connectors
| ID | Pri | Implementation | Verification | Status |
|---|---|---|---|---|
| FR-SRC-001 | Must | `connectors/base.py` contract (fetch/parse/rights/checkpoint), a version on each adapter, `connector_configs.enabled`, registry override | `test_connectors.py` | Done |
| FR-SRC-002 | Must | `connectors/clinicaltrials.py` (API v2, monitored + discovery + incremental `LastUpdatePostDate`); raw + normalized retained | `test_ctgov_*`, `test_us002` (`include_raw` reconstruction + checksum) | Done |
| FR-SRC-003 | Must | `connectors/pubmed.py`: ESearch/EFetch, tool/email/api_key, PMID uniqueness, `query_provenance` | `test_pubmed_*` (cross-query dedup) | Done |
| FR-SRC-004 | Must | `connectors/openfda.py`: Drugs@FDA + SPL labels; FDA disclaimer kept in rights; regulatory events linked to the source document | `test_openfda_label_and_drugsfda_contract`, E2E label change | Done |
| FR-SRC-005 | Should | `SecEdgarAdapter` (8-K/10-K/10-Q/6-K/20-F, primary doc text); permitted IR feeds (`FeedAdapter("corporate")`) | `test_sec_edgar_filters_material_forms` | Done |
| FR-SRC-006 | Should | `FeedAdapter("conference")` with a per-feed rights policy (only public/licensed/permitted feeds are fetched) | `test_feed_rights_policy_enforced` | Partial: generic feed ingestion only; no licensed congress vendor adapter (R2) |
| FR-SRC-007 | Must | Cron schedule per connector (`connector_configs`), beat dispatcher, on-demand `POST /admin/connectors/{key}/run`, health (last success, next run, records, failures) | `test_us008_connector_health_visible` | Done |
| FR-SRC-008 | Must | Content-addressed write-once store; `source_documents` UPDATE blocked by trigger; snapshot links to the document | `test_raw_artifact_reconstruction_and_checksum`, `test_raw_artifacts_are_immutable` | Done |
| FR-SRC-009 | Must | Token bucket per connector (Redis-shared), backoff, `Retry-After`; source-specific defaults (NCBI 3/10 rps, openFDA, SEC UA) | `test_http_retries_on_429…`, `test_rate_limiter_throttles` | Done (load test: see NFR-PERF) |

## 7.3 Canonical data model and entity resolution
| ID | Pri | Implementation | Verification | Status |
|---|---|---|---|---|
| FR-ENT-001 | Must | Company, Asset, Concept (Target, Mechanism, Indication, Biomarker, Endpoint, Modality, Conference, KOL), Trial, Publication, RegulatoryEvent, Catalyst, SourceDocument, ChangeEvent; stable UUIDs independent of source ids | schema / migrations | Done |
| FR-ENT-002 | Must | `EntityResolver`: dev codes, generics, brands, spelling variants; exact → normalized → fuzzy; ambiguous aliases go to review | `test_entities.py`, golden entity set (precision 1.00) | Done |
| FR-ENT-003 | Must | Typed `relationships` (develops, targets, evaluated_in, studies, uses_endpoint, competes_with, authored, received_regulatory_event, …); path finding | `test_graph_traversal_customer_to_trial` | Done |
| FR-ENT-004 | Must | Every link stores confidence + method; below 0.92 → `pending_review`, never auto-promoted | `test_low_confidence_not_promoted…`, `test_dev_codes_never_fuzzy_autolink` | Done |
| FR-ENT-005 | Must | Review queue approve/reject (tenant-scoped or global), merge, split, alias add/remove; all audited; decisions reused by the resolver | `test_rejection_is_honoured`, `test_us006_alias_correction_reused` | Done |
| FR-ENT-006 | Should | Temporal edges (`valid_from`/`valid_to`, `as_of` traversal, `end_edge`); reports snapshot their content at generation time | graph API | Partial: no UI workflow for ownership transfer |

## 7.4 Snapshot and change detection
| ID | Pri | Implementation | Verification | Status |
|---|---|---|---|---|
| FR-CHG-001 | Must | `source_snapshots` versioned only on normalized-hash change; `/trials/{ref}/snapshots`, `/history` | `test_us002_trial_diff_and_history` | Done |
| FR-CHG-002 | Must | `diff_trial` (enrollment, status, phase, endpoints, arms, eligibility, sponsor, dates, locations, conditions, interventions) | `test_acceptance_scenario_emits_three_typed_changes`, golden change set (1.00) | Done |
| FR-CHG-003 | Should | `document_diff` (sentence-level passages, similarity) for labels and eligibility; passages link both snapshot versions | `test_document_diff_highlights_passages`, `test_label_diff_tags_indication_update` | Done |
| FR-CHG-004 | Must | `changes/taxonomy.py`: exactly one primary type (precedence) + secondary tags; field → type map is configurable | `test_acceptance_scenario…` (primary=ENDPOINT_CHANGED) | Done |
| FR-CHG-005 | Must | Canonical comparison (case/punctuation/whitespace/ordering/date formats) plus trivial-edit suppression; suppressed changes kept for audit | `test_formatting_and_ordering_changes_are_suppressed`, golden noise set (1.00) | Done |
| FR-CHG-006 | Must | Change fingerprint unique (ON CONFLICT DO NOTHING); intel-event fingerprint per landscape; row locks | `test_reruns_are_idempotent` | Done |

## 7.5 Materiality and impact
| ID | Pri | Implementation | Verification | Status |
|---|---|---|---|---|
| FR-MAT-001 | Must | R, C, P, T, N dimensions, 0-100, configurable weights, magnitude gate | `test_materiality.py` | Done |
| FR-MAT-002 | Must | Archive / Feed / Analyst Review / High Priority / Executive Alert; per-landscape thresholds (`PUT /landscapes/{id}/thresholds`) | `test_bands_are_configurable_per_landscape` | Done |
| FR-MAT-003 | Must | `materiality/mapping.py`: proximity rules + graph path (customer → competes_with → competitor → evaluated_in → trial) with rationale | E2E path assertion | Done |
| FR-MAT-004 | Must | `score_components`: per-dimension score, weight, contribution, rule hits, model confidence, gate | `test_acceptance_scenario_is_executive_alert_with_explanation` | Done |
| FR-MAT-005 | Should | Frozen versioned `feedback_datasets`; threshold suggestions; `model_releases` evaluated on the dataset, promotion gated on regression; raw labels untouched | `test_threshold_tuning…`, `test_us010` | Partial: threshold tuning only; no learned ranker yet (planned for R4) |
| FR-MAT-006 | Could | `personalize=true`: watchlist-based ranking boost only; never changes facts or scores | `test_feed_filters_and_personalization` | Done |

## 7.6 Intelligence reasoning and evidence
| ID | Pri | Implementation | Verification | Status |
|---|---|---|---|---|
| FR-AI-001 | Must | `statement_type` FACT / INFERENCE / UNKNOWN / RECOMMENDED_INVESTIGATION in API + DB + UI | E2E, `test_us003…` | Done |
| FR-AI-002 | Must | Grounded generation over S*/C*/E* evidence; unsupported FACTs withheld | `test_validator_withholds…`, golden unsupported-fact rate 0.00 | Done |
| FR-AI-003 | Must | `evidence_links`: source, type, source document, snapshot, chunk, field path, span, retrieved_at, rights; `/sources/chunks/{id}` context | E2E provenance assertions, `test_us005` | Done |
| FR-AI-004 | Must | Impact narrative sections: what changed / why it may matter / affected assets / limitations / investigation | E2E | Done |
| FR-AI-005 | Must | Policy-based confidence (`enforce_confidence_policy`); no numeric pseudo-probabilities | `test_validator_withholds…` | Done |
| FR-AI-006 | Must | Evidence Agent (deterministic + independent judge); high-severity unsupported → blocked; deterministic fallback | `test_hallucinating_model_output_is_blocked…`, golden hallucination block rate 1.00 | Done |
| FR-AI-007 | Must | `generation_records` (model, served model, prompt id/version/hash, workflow version, config, retrieval-set manifest + hash) | `test_claude_request_shape_and_governance`, `test_us009` | Done |
| FR-AI-008 | Must | Abstention in Ask; UNKNOWN statements in narratives | `test_abstains_when_evidence_insufficient`, golden abstention 1.00 | Done |

## 7.7-7.10 Experience, Ask, alerts, feedback
| ID | Pri | Implementation | Verification | Status |
|---|---|---|---|---|
| FR-UX-001 | Must | `GET /dashboard` + Home screen | `test_us008…` | Done |
| FR-UX-002 | Must | `GET /events` with every filter as a query param (bookmarkable); `/events/facets` | `test_feed_filters_and_personalization` | Done |
| FR-UX-003 | Must | `/landscapes/{id}/matrix`: every populated cell has provenance | `test_matrix_comparison_and_calendar` | Done |
| FR-UX-004 | Must | `/comparisons` + context warnings (indirect, differing endpoints/populations) + export | same | Done |
| FR-UX-005 | Must | `/catalysts`: SOURCED vs INFERRED, changed dates with history | same, `test_catalysts_track_changed_dates` | Done |
| FR-UX-006 | Must | `/events/{id}`: diff, source, score explanation, impact path, claims + evidence, unknowns, feedback, history | `test_us002`, `test_us003` | Done |
| FR-UX-007 | Should | `/saved-views` private/team/tenant; the viewer's own permissions still apply | `test_feed_filters…` | Done |
| FR-QA-001 | Must | `/ask`, tenant-scoped retrieval (RLS) | `test_hybrid_retrieval_relevance_and_tenant_isolation` | Done |
| FR-QA-002 | Must | Answer contract: answer, statements (evidence), sources, confidence, limitations, comparison_warning | `test_us007` | Done |
| FR-QA-003 | Must | Change-history channel (C*) with time-window parsing; superseded chunks retrievable | `test_temporal_question_uses_version_history`, `test_history_retrievable_but_not_current` | Done |
| FR-QA-004 | Must | Comparison detection + enforced indirect-comparison warning | `test_comparison_question_warns_indirect` | Done |
| FR-QA-005 | Should | `ask_sessions.context` referents/filters, bound to user + tenant | `test_session_memory_referents_and_boundaries` | Done |
| FR-QA-006 | Should | DOCX / PDF / PPTX / Markdown export with sources + timestamp | `test_us007` | Done |
| FR-ALT-001 | Must | Immediate/daily/weekly policies by score, types, entities, watchlist; `/preview` estimates volume from history | `test_alert_policy_preview_and_digest_dedup` | Done |
| FR-ALT-002 | Must | Appendix B payload (`alert_payload`): change, why flagged, affected asset, known, unknown, interpretation, investigation, evidence, materiality, review status, link | E2E notification assertions | Done |
| FR-ALT-003 | Must | Briefing Agent; draft → edit → approve → distribute (distribution before approval is refused) | `test_executive_brief_review_before_distribution` | Done |
| FR-ALT-004 | Should | web, email (SMTP/TLS), Slack, Teams (Adaptive Card), HMAC-signed webhook; retries with backoff, dead-lettering, logging | `alerts/channels.py`, `deliver_pending` | Done |
| FR-ALT-005 | Must | `notified_event_state` per policy/event version; updates carry `update_summary` | `test_alert_policy_preview_and_digest_dedup` | Done |
| FR-FBK-001 | Must | 8 labels + reason + comment + user + timestamp + event version | `test_us010` | Done |
| FR-FBK-002 | Must | Human edits create a new artifact (`parent_id`); original + evidence untouched; FACT edits must cite existing evidence | `test_us009_audit_of_edits_and_generation` | Done |
| FR-FBK-003 | Should | Frozen versioned datasets with content hash; releases reference the dataset | `test_us010` | Done |

## 8-9 Data and API requirements
| Item | Implementation | Status |
|---|---|---|
| §8.1 entities | All minimum fields present (`app/models/*`) | Done |
| §8.2 provenance | Source system + id on every record; snapshot retrieval time + raw ref; claims → evidence or typed as inference/unknown; corrections audited with before/after/reason; artifacts keep `evidence_snapshot_ids` | Done |
| §9 API | `/api/v1` versioned; bearer auth; RBAC; pagination; `Idempotency-Key` on creates; OpenAPI (`docs/openapi.json`) | Done (`test_idempotent_mutation`, `test_openapi_documented`) |

## 10 Non-functional
| ID | Implementation | Verification | Status |
|---|---|---|---|
| NFR-SEC-001 | Postgres RLS (FORCE, strict + shared policies) + application filters; dedicated deployment mode (`tenants.deployment_mode`, separate stack via Terraform/kustomize) | `test_cross_tenant_api_isolation`, `test_rls_blocks_cross_tenant_rows_at_database_level`, RAG forged-tenant test | Done |
| NFR-SEC-002 | OIDC SSO (JWKS validation, tenant + role claims, JIT provisioning, `amr` MFA enforcement); local login for bootstrap; API keys | `test_unauthenticated…`, `test_api_keys…` | Partial: SAML via an IdP/broker that issues OIDC (Okta/Entra/Keycloak); no native SAML SP |
| NFR-SEC-003 | `core/rbac.py` roles → permissions; server-side `require()` on every route | `test_rbac_enforced_server_side` | Done |
| NFR-SEC-004 | TLS (ingress, RDS, ElastiCache TLS); KMS at rest (RDS, S3, Redis); Fernet encryption of webhook/credential fields; log redaction | `test_alert_destinations_encrypted_at_rest`, `test_secrets_not_logged` | Done |
| NFR-SEC-005 | Secrets Manager → ExternalSecrets; production refuses dev secrets; gitleaks in CI + pre-commit | `.github/workflows/ci.yml`, `core/config.py` guards | Done |
| NFR-AUD-001 | Hash-chained `audit_log`, no UPDATE/DELETE policies + trigger; export CSV/JSON; `/audit/verify` | `test_audit_log_is_append_only_and_hash_chained` | Done |
| NFR-REL-001 | Multi-AZ RDS, HPA/PDB, readiness probes; connector availability kept separate from app SLO in the dashboard | `deploy/` | Done (SLO measurement needs production traffic) |
| NFR-PERF-001 | Indexed queries (GIN/HNSW/btree), pagination, SSE streaming for AI | — | Partial: no load test run in this repo yet (see runbook §Performance) |
| NFR-ALT-001 | 60 s processing cadence; per-event latency record + Prometheus histogram + alert rule | E2E asserts fetch → alert < 15 min | Done |
| NFR-SCL-001 | Stateless API, queue-separated workers, shared rate limits, advisory locks | architecture | Partial: 10× load test pending |
| NFR-OBS-001 | Prometheus metrics (API, connectors, changes, events, LLM, retrieval, validation, alerts, pipeline latency), JSON logs with request ids, OTel traces, Grafana dashboard + alert rules | `/metrics`, `deploy/observability` | Done |
| NFR-DR-001 | RDS PITR (RPO 15 min), snapshots, S3 versioning + Object Lock, pg_dump CronJob, quarterly restore procedure | `deploy/README.md`, `docs/runbook.md` | Done (procedure; first restore test is an ops task) |
| NFR-PRV-001 | Retention per data class per tenant (`PATCH /admin/settings`), nightly purge task | `workers/tasks.retention_task` | Done |
| NFR-AI-001 | `generation_records` (model, version, prompt/workflow, effort/config, retrieval context) | `test_claude_request_shape_and_governance` | Done |
| NFR-AI-002 | No training on customer data: no fine-tuning pipeline; `allow_training_on_customer_data=false` surfaced in admin | admin `/models` | Done (vendor terms review is a contractual task) |
| NFR-ACC-001 | Semantic HTML, labels, keyboard, aria-live, text labels alongside colour (frontend) | frontend tests | Partial: formal WCAG audit before GA |

## Section 16 acceptance scenario
Covered step by step (ingest → learn) by `test_pipeline_e2e.py::test_acceptance_scenario_end_to_end` and reproducible
with `python -m app.cli seed-demo`.

## Section 18 metrics (golden suite, offline, v1.0.0)
Every threshold passes: change detection 1.00, noise suppression 1.00, entity precision 1.00 / recall 1.00, material
recall 1.00, high-priority precision 1.00, attribution 1.00, unsupported facts 0.00, hallucination blocking 1.00,
abstention 1.00. **Caveat:** this golden set is illustrative. SRS §19.1 requires the customer's 3-6 month
retrospective set before launch, and analyst time reduction and user-rated usefulness can only be measured during
the pilot (`GET /kpis`).

## Explainable AI (added requirement)
| Item | Implementation | Verification | Status |
|---|---|---|---|
| NIST IR 8312 principles (explanation, meaningful, explanation accuracy, knowledge limits) | `app/ai/explain.py`; `GET /events/{id}/explanation`; Ask `explanation` trace; `GET /auth/ai-transparency`; UI "Why am I seeing this?" panel, answer trace, AI transparency page | `test_explainability.py` (recomputes the score from the explained drivers), `ExplanationPanel.test.tsx`, E2E smoke | Done |
