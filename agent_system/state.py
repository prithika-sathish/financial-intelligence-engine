from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    query: str
    predictions: list[dict[str, Any]]
    graph_summary: dict[str, Any]
    news_signals: list[dict[str, Any]]
    temporal_trends: list[dict[str, Any]]
    network_risk: list[dict[str, Any]]
    graph_insights: dict[str, Any]
    answer: str
    alerts: list[dict[str, Any]]
