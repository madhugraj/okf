from __future__ import annotations

from dataclasses import asdict
import json

from okf_platform.corpus import LocalCorpusStore
from okf_platform.knowledge_service import KnowledgeService
from okf_platform.models import FetchResponse
from okf_platform.okf_core import OKF_VERSION, build_okf, load_okf_bundle, query_okf
from okf_platform.rag import RAG_VERSION, build_rag_index, query_rag
from okf_platform.rag_runtime import RagRuntime, RagRuntimeConfig
from okf_platform.snapshot import canonical_hash
from okf_platform.vector_store import DenseMatch


class SemanticFixtureEncoder:
    name = "semantic-fixture/1.0"
    dimensions = 3
    minimum_similarity = 0.8

    def embed_documents(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]

    def embed_query(self, text):
        del text
        return [1.0, 0.0, 0.0]


class SemanticFixtureReranker:
    name = "semantic-reranker-fixture/1.0"

    def score(self, question, documents):
        del question
        return [1.0 for _ in documents]


class MemoryVectorStore:
    name = "memory-vector-store/1.0"

    def __init__(self):
        self.rows = {}

    def replace(self, corpus_id, index_version, embedding_version, chunks, vectors):
        key = (corpus_id, index_version, embedding_version)
        self.rows[key] = {
            str(chunk["id"]): list(vector)
            for chunk, vector in zip(chunks, vectors, strict=True)
        }

    def search(
        self,
        corpus_id,
        index_version,
        embedding_version,
        query_vector,
        *,
        filters,
        limit,
    ):
        del filters
        rows = self.rows[(corpus_id, index_version, embedding_version)]
        matches = [
            DenseMatch(chunk_id, sum(a * b for a, b in zip(vector, query_vector, strict=True)))
            for chunk_id, vector in rows.items()
        ]
        return sorted(matches, key=lambda item: -item.score)[:limit]

    def count(self, corpus_id, index_version, embedding_version):
        return len(self.rows.get((corpus_id, index_version, embedding_version), {}))


def _approved_corpus(tmp_path) -> tuple[str, str]:
    corpus_id = "corpus-fixture"
    url = "https://example.com/services.html"
    body = (
        b"<h1>AISATS Services</h1>"
        b"<p>AISATS provides ground handling services at Bengaluru Airport. "
        b"AISATS operates cargo terminals in India. The company serves airlines.</p>"
    )
    asset = LocalCorpusStore(tmp_path / "corpus").save(
        "run-fixture",
        FetchResponse(url, url, 200, {"content-type": "text/html"}, body),
        referring_url="https://example.com/",
        discovered_by="test",
    )
    item = {
        key: value.value if hasattr(value, "value") else value
        for key, value in asdict(asset).items()
        if key
        in {
            "sha256",
            "kind",
            "byte_size",
            "detected_mime",
            "extension",
            "storage_uri",
        }
    }
    observation = {
        key: value.value if hasattr(value, "value") else value
        for key, value in asdict(asset).items()
    }
    core = {
        "schema_version": "okf-corpus-snapshot/1.0",
        "corpus_id": corpus_id,
        "target_url": "https://example.com/",
        "source_run_id": "run-fixture",
        "baseline_run_id": "run-baseline",
        "approved_at": "2026-07-21T00:00:00+00:00",
        "approved_by": "Madhu",
        "crawl_report_sha256": "c" * 64,
        "qa_effective_verdict": "pass",
        "accepted_qa_exceptions": [],
        "objects": [item],
        "observations": [observation],
    }
    snapshot = {**core, "manifest_sha256": canonical_hash(core)}
    destination = tmp_path / "corpora" / corpus_id / "manifest.json"
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(snapshot), encoding="utf-8")
    return corpus_id, url


def test_okf_builds_versioned_claims_and_exact_evidence(tmp_path) -> None:
    corpus_id, url = _approved_corpus(tmp_path)
    manifest = build_okf(tmp_path, corpus_id)
    bundle = load_okf_bundle(tmp_path, corpus_id)

    assert manifest["okf_version"] == OKF_VERSION
    assert manifest["counts"]["claims"] == 3
    assert manifest["counts"]["entities"] >= 3
    assert bundle["corpus"]["id"] == corpus_id
    claim = next(item for item in bundle["claims"] if "ground handling" in item["statement"])
    evidence = claim["evidence"][0]
    assert evidence["quote"] == claim["statement"]
    assert evidence["source_url"] == url
    assert claim["validation"] == "exact_evidence_verified"
    assert build_okf(tmp_path, corpus_id) == manifest


def test_okf_query_answers_from_claims_and_abstains_without_evidence(tmp_path) -> None:
    corpus_id, url = _approved_corpus(tmp_path)
    answer = query_okf(tmp_path, corpus_id, "What ground handling services does AISATS provide?")

    assert answer["status"] == "answered"
    assert "ground handling" in answer["answer"]
    assert answer["citations"][0]["source_url"] == url
    assert query_okf(tmp_path, corpus_id, "quantum entanglement research")["status"] == "abstained"


def test_rag_builds_independent_hybrid_index_and_verified_citations(tmp_path) -> None:
    corpus_id, url = _approved_corpus(tmp_path)
    manifest = build_rag_index(tmp_path, corpus_id)
    answer = query_rag(tmp_path, corpus_id, "Where does AISATS operate cargo terminals?")

    assert manifest["rag_version"] == RAG_VERSION
    assert manifest["chunk_count"] >= 1
    assert manifest["embedding_version"] == "deterministic-feature-hash/1.0"
    assert answer["status"] == "answered"
    assert answer["citations"][0]["source_url"] == url
    assert "cargo terminals" in answer["citations"][0]["quote"]
    assert query_rag(
        tmp_path,
        corpus_id,
        "cargo terminals",
        filters={"kind": "pdf"},
    )["status"] == "abstained"


def test_common_service_compares_and_evaluates_same_corpus(tmp_path) -> None:
    corpus_id, _ = _approved_corpus(tmp_path)
    service = KnowledgeService(tmp_path)
    assert service.build_okf(corpus_id)["critic"]["verdict"] == "pass"
    assert service.build_rag(corpus_id)["critic"]["verdict"] == "pass"
    comparison = service.compare(corpus_id, "What services does AISATS provide?")

    assert comparison["same_corpus"] is True
    assert comparison["okf"]["status"] == "answered"
    assert comparison["rag"]["status"] == "answered"
    evaluation = service.evaluate(
        corpus_id,
        [
            {
                "id": "services",
                "question": "What services does AISATS provide?",
                "expected_terms": ["ground handling"],
            }
        ],
    )
    assert evaluation["summary"]["okf"]["case_count"] == 1
    assert evaluation["summary"]["rag"]["case_count"] == 1
    assert (
        tmp_path
        / "evaluations"
        / corpus_id
        / f"{evaluation['evaluation_id']}.json"
    ).is_file()


def test_semantic_dense_retrieval_answers_without_bm25_word_overlap(tmp_path) -> None:
    corpus_id, url = _approved_corpus(tmp_path)
    encoder = SemanticFixtureEncoder()
    reranker = SemanticFixtureReranker()
    store = MemoryVectorStore()
    manifest = build_rag_index(
        tmp_path, corpus_id, encoder=encoder, vector_store=store
    )

    answer = query_rag(
        tmp_path,
        corpus_id,
        "Which apron assistance options exist?",
        encoder=encoder,
        reranker=reranker,
        vector_store=store,
    )

    assert manifest["vector_backend"] == store.name
    assert manifest["embedding_dimensions"] == 3
    assert answer["status"] == "answered"
    assert answer["citations"][0]["source_url"] == url
    assert answer["trace"]["reranker_version"] == reranker.name


def test_rag_service_exposes_runtime_and_ranking_metrics(tmp_path) -> None:
    corpus_id, url = _approved_corpus(tmp_path)
    config = RagRuntimeConfig(
        sparse_candidates=40,
        dense_candidates=40,
        rerank_candidates=20,
        final_passages=8,
    )
    runtime = RagRuntime(
        config,
        SemanticFixtureEncoder(),
        SemanticFixtureReranker(),
        MemoryVectorStore(),
    )
    service = KnowledgeService(tmp_path, runtime)
    service.build_rag(corpus_id)
    evaluation = service.evaluate(
        corpus_id,
        [
            {
                "question": "Which apron assistance options exist?",
                "expected_source_urls": [url],
            }
        ],
    )

    assert service.rag_config()["retrieval"]["sparse"] == "BM25"
    assert evaluation["summary"]["rag"]["average_recall_at_5"] == 1.0
    assert evaluation["summary"]["rag"]["average_mrr"] == 1.0
    assert evaluation["summary"]["rag"]["average_ndcg_at_10"] == 1.0
