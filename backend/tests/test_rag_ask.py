"""RAG retrieval (hybrid, tenant-scoped, temporal) and Ask-the-Landscape answer contract (FR-QA-*)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.ai.agents.ask import ask, parse_time_window
from app.connectors.base import TextSection
from app.db.session import session_scope
from app.models import AskSession, SourceDocument
from app.rag.chunking import chunk_text
from app.rag.embeddings import HashingEmbedder
from app.rag.indexer import index_sections
from app.rag.retriever import HybridRetriever, RetrievalQuery


def test_chunking_respects_budget_and_offsets():
    text = " ".join(f"Sentence number {i} describes the trial design and endpoints." for i in range(200))
    chunks = chunk_text(text, max_tokens=120, overlap_tokens=20)
    assert len(chunks) > 5
    assert all(c.token_count <= 130 for c in chunks)
    assert all(text[c.char_start:c.char_end] == c.text for c in chunks)


def test_hashing_embedder_semantics():
    e = HashingEmbedder(256)
    q = e.embed_query("objective response rate in Target-X NSCLC")
    near = e.embed_documents(["The objective response rate was 41% in Target-X mutant NSCLC."])[0]
    far = e.embed_documents(["Quarterly revenue guidance for the fiscal year."])[0]
    dot = lambda a, b: sum(x * y for x, y in zip(a, b, strict=True))  # noqa: E731
    assert dot(q, near) > dot(q, far)


def _private_doc(db, tenant_id, text):  # type: ignore[no-untyped-def]
    doc = SourceDocument(source="internal", source_object_id=uuid.uuid4().hex, uri="internal://doc", checksum=uuid.uuid4().hex * 2,
                         storage_key="x", byte_size=1, retrieved_at=datetime.now(UTC), connector_key="internal",
                         connector_version="1", rights={"license": "customer-confidential"}, title="Internal memo")
    db.add(doc)
    db.flush()
    index_sections(db, source_document=doc, object_type="internal_note", object_id=None,
                   sections=[TextSection("memo", "memo.body", text, "Internal memo")], tenant_id=tenant_id)


def test_hybrid_retrieval_relevance_and_tenant_isolation(demo_pipeline, second_tenant):
    a, b = demo_pipeline["tenant_id"], second_tenant["tenant_id"]
    with session_scope(bypass_rls=True) as db:
        _private_doc(db, a, "Confidential: XD-101 CNS penetration strategy and go/no-go criteria for Phase 3.")
    with session_scope(a) as db:
        hits = HybridRetriever(db).search(RetrievalQuery(text="XD-101 CNS penetration strategy", tenant_id=a))
        assert any("CNS penetration" in h.text for h in hits)
        pubs = HybridRetriever(db).search(RetrievalQuery(text="zelvatinib objective response rate", tenant_id=a))
        assert pubs and pubs[0].source == "pubmed" and "41%" in pubs[0].text
    with session_scope(b) as db:  # RLS + retriever filter: tenant B never sees tenant A's private chunk
        hits = HybridRetriever(db).search(RetrievalQuery(text="XD-101 CNS penetration strategy", tenant_id=b))
        assert not any("CNS penetration" in h.text for h in hits)
    with session_scope(b) as db:  # even if the caller forges tenant_id, RLS still hides the row
        hits = HybridRetriever(db).search(RetrievalQuery(text="XD-101 CNS penetration strategy", tenant_id=a))
        assert not any("CNS penetration" in h.text for h in hits)


def test_history_retrievable_but_not_current(demo_pipeline):
    tid = demo_pipeline["tenant_id"]
    with session_scope(tid) as db:
        cur = HybridRetriever(db).search(RetrievalQuery(text="NCT99000001 enrollment 320", tenant_id=tid))
        hist = HybridRetriever(db).search(RetrievalQuery(text="NCT99000001 enrollment 320", tenant_id=tid,
                                                          current_only=False))
        assert not any("Enrollment: 320" in h.text for h in cur)
        assert any("Enrollment: 320" in h.text and not h.is_current for h in hist)


def test_time_window_parsing():
    now = datetime(2026, 9, 25, 12, tzinfo=UTC)  # Friday
    s, _ = parse_time_window("what changed this week?", now)
    assert s == datetime(2026, 9, 21, tzinfo=UTC)
    s, _ = parse_time_window("timelines moved in the past 14 days", now)
    assert s == now - timedelta(days=14)
    assert parse_time_window("what is the mechanism of CA-201", now) == (None, None)


def test_temporal_question_uses_version_history(demo_pipeline):
    tid, uid = demo_pipeline["tenant_id"], demo_pipeline["users"]["analyst@demo.example"]
    with session_scope(tid) as db:
        out = ask(db, tenant_id=tid, user_id=uid, question="What changed this week in my landscape?",
                  landscape_id=demo_pipeline["landscape_id"])
    assert not out["abstained"]
    facts = [s for s in out["statements"] if s["statement_type"] == "FACT"]
    assert facts and all(s["evidence_ids"] for s in facts)
    assert any(e.startswith("C") for s in facts for e in s["evidence_ids"])  # change records, not current state
    assert any("480" in s["statement"] for s in facts)
    assert {"answer", "statements", "sources", "confidence", "limitations"} <= set(out)


def test_comparison_question_warns_indirect(demo_pipeline):
    tid, uid = demo_pipeline["tenant_id"], demo_pipeline["users"]["analyst@demo.example"]
    with session_scope(tid) as db:
        out = ask(db, tenant_id=tid, user_id=uid, question="Compare XD-101 versus CA-201",
                  landscape_id=demo_pipeline["landscape_id"])
    assert "indirect" in out["comparison_warning"].lower()
    assert set(out["resolved_context"]["entity_labels"].values()) >= {"XD-101", "CA-201"}


def test_abstains_when_evidence_insufficient(demo_pipeline):
    tid, uid = demo_pipeline["tenant_id"], demo_pipeline["users"]["analyst@demo.example"]
    with session_scope(tid) as db:
        out = ask(db, tenant_id=tid, user_id=uid, question="What is the price of a pastry in Lisbon bakeries?")
    assert out["abstained"] and out["confidence"] == "Not applicable"
    assert not [s for s in out["statements"] if s["statement_type"] == "FACT"]


def test_session_memory_referents_and_boundaries(demo_pipeline):
    tid, uid = demo_pipeline["tenant_id"], demo_pipeline["users"]["analyst@demo.example"]
    other_user = demo_pipeline["users"]["cso@demo.example"]
    with session_scope(tid) as db:
        first = ask(db, tenant_id=tid, user_id=uid, question="Compare CA-201 and CDR-44",
                    landscape_id=demo_pipeline["landscape_id"])
        second = ask(db, tenant_id=tid, user_id=uid, question="What are their primary endpoints?",
                     session_id=uuid.UUID(first["session_id"]))
        assert second["session_id"] == first["session_id"]
        assert set(second["resolved_context"]["entity_labels"].values()) == {"CA-201", "CDR-44"}
        # another user cannot continue this session: a fresh session is created instead
        third = ask(db, tenant_id=tid, user_id=other_user, question="What are their primary endpoints?",
                    session_id=uuid.UUID(first["session_id"]))
        assert third["session_id"] != first["session_id"]
        assert db.get(AskSession, uuid.UUID(third["session_id"])).user_id == other_user
