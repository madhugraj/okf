"""LangGraph wrapper around deterministic crawl and reconciliation nodes."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from .crawler import CrawlEngine
from .models import CrawlReport


class DiscoveryState(TypedDict):
    target_url: str
    seed_urls: NotRequired[list[str]]
    report: NotRequired[CrawlReport]
    ready: NotRequired[bool]


def build_discovery_graph(engine: CrawlEngine):
    """Build the bounded M1 graph; importing LangGraph is deferred for testability."""

    from langgraph.graph import END, START, StateGraph

    def crawl(state: DiscoveryState) -> DiscoveryState:
        return {
            **state,
            "report": engine.run(state["target_url"], seed_urls=state.get("seed_urls")),
        }

    def reconcile(state: DiscoveryState) -> DiscoveryState:
        report = state["report"]
        return {**state, "ready": report.ready_for_reconciliation and not report.budget_exhausted}

    graph = StateGraph(DiscoveryState)
    graph.add_node("crawl", crawl)
    graph.add_node("reconcile", reconcile)
    graph.add_edge(START, "crawl")
    graph.add_edge("crawl", "reconcile")
    graph.add_edge("reconcile", END)
    return graph.compile()
