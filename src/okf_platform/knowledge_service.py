"""Separate OKF and RAG agents plus a common comparison service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter
from typing import NotRequired, TypedDict

from .knowledge_io import atomic_json, stable_id
from .okf_core import audit_okf, build_okf, query_okf
from .rag import audit_rag_index, build_rag_index, query_rag


class BuildState(TypedDict):
    data_dir: Path
    corpus_id: str
    manifest: NotRequired[dict[str, object]]
    critic: NotRequired[dict[str, object]]


def build_okf_agent():
    """OKF-only graph; it has no RAG index access."""

    from langgraph.graph import END, START, StateGraph

    def transform_and_validate(state: BuildState) -> BuildState:
        return {**state, "manifest": build_okf(state["data_dir"], state["corpus_id"])}

    def critic(state: BuildState) -> BuildState:
        return {**state, "critic": audit_okf(state["data_dir"], state["corpus_id"])}

    graph = StateGraph(BuildState)
    graph.add_node("extract_claims_entities_and_evidence", transform_and_validate)
    graph.add_node("independent_evidence_critic", critic)
    graph.add_edge(START, "extract_claims_entities_and_evidence")
    graph.add_edge("extract_claims_entities_and_evidence", "independent_evidence_critic")
    graph.add_edge("independent_evidence_critic", END)
    return graph.compile()


def build_rag_agent():
    """RAG-only graph; it receives extraction units, never OKF claims."""

    from langgraph.graph import END, START, StateGraph

    def chunk_index_and_validate(state: BuildState) -> BuildState:
        return {**state, "manifest": build_rag_index(state["data_dir"], state["corpus_id"])}

    def critic(state: BuildState) -> BuildState:
        return {**state, "critic": audit_rag_index(state["data_dir"], state["corpus_id"])}

    graph = StateGraph(BuildState)
    graph.add_node("build_hybrid_parent_child_index", chunk_index_and_validate)
    graph.add_node("independent_index_critic", critic)
    graph.add_edge(START, "build_hybrid_parent_child_index")
    graph.add_edge("build_hybrid_parent_child_index", "independent_index_critic")
    graph.add_edge("independent_index_critic", END)
    return graph.compile()


@dataclass(slots=True)
class KnowledgeService:
    data_dir: Path

    def build_okf(self, corpus_id: str) -> dict[str, object]:
        state = build_okf_agent().invoke(
            {"data_dir": self.data_dir, "corpus_id": corpus_id}
        )
        return {**state["manifest"], "critic": state["critic"]}

    def build_rag(self, corpus_id: str) -> dict[str, object]:
        state = build_rag_agent().invoke(
            {"data_dir": self.data_dir, "corpus_id": corpus_id}
        )
        return {**state["manifest"], "critic": state["critic"]}

    def compare(
        self,
        corpus_id: str,
        question: str,
        *,
        filters: dict[str, object] | None = None,
    ) -> dict[str, object]:
        started = perf_counter()
        okf_result = query_okf(self.data_dir, corpus_id, question)
        okf_ms = (perf_counter() - started) * 1_000
        started = perf_counter()
        rag_result = query_rag(self.data_dir, corpus_id, question, filters=filters)
        rag_ms = (perf_counter() - started) * 1_000
        okf_result["latency_ms"] = round(okf_ms, 3)
        rag_result["latency_ms"] = round(rag_ms, 3)
        return {
            "schema_version": "okf-rag-comparison/1.0",
            "corpus_id": corpus_id,
            "question": question,
            "same_corpus": True,
            "okf": okf_result,
            "rag": rag_result,
        }

    def evaluate(
        self, corpus_id: str, cases: list[dict[str, object]]
    ) -> dict[str, object]:
        if not cases:
            raise ValueError("at least one evaluation case is required")
        results = []
        for case in cases:
            question = str(case.get("question", "")).strip()
            if not question:
                raise ValueError("every evaluation case requires a question")
            comparison = self.compare(corpus_id, question, filters=case.get("filters"))
            expected_terms = {
                str(term).casefold() for term in case.get("expected_terms", []) if str(term).strip()
            }
            expected_sources = {
                str(url) for url in case.get("expected_source_urls", []) if str(url).strip()
            }
            methods = {}
            for method in ("okf", "rag"):
                result = comparison[method]
                answer = str(result.get("answer") or "").casefold()
                actual_sources = {
                    str(item.get("source_url"))
                    for item in result.get("citations", [])
                    if item.get("source_url")
                }
                methods[method] = {
                    "answered": result["status"] == "answered",
                    "citation_count": len(result.get("citations", [])),
                    "citation_validity": (
                        1.0 if result.get("citations") else None
                    ),
                    "expected_term_recall": (
                        sum(term in answer for term in expected_terms) / len(expected_terms)
                        if expected_terms
                        else None
                    ),
                    "expected_source_recall": (
                        len(expected_sources & actual_sources) / len(expected_sources)
                        if expected_sources
                        else None
                    ),
                    "latency_ms": result["latency_ms"],
                }
            results.append(
                {
                    "id": case.get("id") or f"case-{len(results) + 1}",
                    "question": question,
                    "comparison": comparison,
                    "metrics": methods,
                }
            )
        summary = {}
        for method in ("okf", "rag"):
            method_metrics = [item["metrics"][method] for item in results]
            citation_scores = [
                float(item["citation_validity"])
                for item in method_metrics
                if item["citation_validity"] is not None
            ]
            term_scores = [
                float(item["expected_term_recall"])
                for item in method_metrics
                if item["expected_term_recall"] is not None
            ]
            source_scores = [
                float(item["expected_source_recall"])
                for item in method_metrics
                if item["expected_source_recall"] is not None
            ]
            summary[method] = {
                "case_count": len(results),
                "answered_rate": sum(item["answered"] for item in method_metrics) / len(results),
                "abstention_rate": 1
                - sum(item["answered"] for item in method_metrics) / len(results),
                "citation_validity_rate": (
                    sum(citation_scores) / len(citation_scores) if citation_scores else None
                ),
                "average_expected_term_recall": (
                    sum(term_scores) / len(term_scores) if term_scores else None
                ),
                "average_expected_source_recall": (
                    sum(source_scores) / len(source_scores) if source_scores else None
                ),
                "average_latency_ms": round(
                    sum(float(item["latency_ms"]) for item in method_metrics) / len(results), 3
                ),
                "total_citations": sum(int(item["citation_count"]) for item in method_metrics),
            }
        evaluation_id = stable_id(
            "evaluation", corpus_id, json.dumps(cases, sort_keys=True, separators=(",", ":"))
        )
        evaluation = {
            "schema_version": "okf-rag-evaluation/1.0",
            "evaluation_id": evaluation_id,
            "corpus_id": corpus_id,
            "fairness_rule": "same immutable corpus snapshot and typed extraction",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "cases": results,
        }
        atomic_json(self.data_dir / "evaluations" / corpus_id / f"{evaluation_id}.json", evaluation)
        return evaluation
