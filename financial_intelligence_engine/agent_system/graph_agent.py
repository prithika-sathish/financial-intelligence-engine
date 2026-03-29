from __future__ import annotations

import logging
from typing import Any

from agent_system.state import AgentState
from configs.settings import get_settings
from graph_engine.neo4j_client import neo4j_session

try:
    from langchain_groq import ChatGroq
except Exception:  # pragma: no cover
    ChatGroq = None

try:
    from langgraph.graph import END, START, StateGraph
except Exception:  # pragma: no cover
    END = "END"
    START = "START"
    StateGraph = None

LOGGER = logging.getLogger(__name__)


def _llm_failure_fallback_answer(state: AgentState) -> str:
    predictions = state.get("predictions", []) or []
    risk_key = "propagated_risk" if any("propagated_risk" in p for p in predictions if isinstance(p, dict)) else "risk_score"
    ranked = sorted(
        [p for p in predictions if isinstance(p, dict)],
        key=lambda row: float(row.get(risk_key, 0.0) or 0.0),
        reverse=True,
    )
    top_companies = [str(row.get("company_id")) for row in ranked[:3] if row.get("company_id")]

    graph_insights = state.get("graph_insights", {}) or {}
    anomaly_total = 0
    for supplier in graph_insights.get("abnormal_suppliers", []) or []:
        try:
            anomaly_total += int(float(supplier.get("tx_count", 0) or 0))
        except Exception:
            continue

    companies_text = ", ".join(top_companies) if top_companies else "N/A"
    return (
        f"Top risk companies: {companies_text}\n"
        f"Total anomalies: {anomaly_total}\n"
        "Risk signals detected from transactions and network patterns."
    )


def _query_neo4j_insights() -> dict[str, Any]:
    insights: dict[str, Any] = {
        "abnormal_suppliers": [],
        "top_risky_companies": [],
        "negative_events": [],
        "dry_run": False,
    }
    with neo4j_session() as session:
        if session is None:
            insights["dry_run"] = True
            return insights
        try:
            abnormal = session.run(
                """
                MATCH (:Company)-[:COMPANY_PAYS_SUPPLIER]->(s:Supplier), (a:Account)-[:ACCOUNT_EXECUTES_TRANSACTION]->(t:Transaction)
                WHERE t.anomaly_flag = 1
                RETURN s.supplier_id AS supplier_id, avg(t.anomaly_score) AS avg_anomaly_score, count(t) AS tx_count
                ORDER BY avg_anomaly_score DESC, tx_count DESC
                LIMIT 5
                """
            )
            insights["abnormal_suppliers"] = [dict(r) for r in abnormal]
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("Failed abnormal supplier query: %s", exc)

        try:
            neg_events = session.run(
                """
                MATCH (c:Company)-[:COMPANY_AFFECTED_BY_EVENT]->(e:Event)
                WHERE e.sentiment = 'negative'
                RETURN c.company_id AS company_id, e.event_type AS event_type, e.trigger AS trigger
                LIMIT 10
                """
            )
            insights["negative_events"] = [dict(r) for r in neg_events]
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("Failed negative event query: %s", exc)

    return insights


def _rule_based_answer(state: AgentState) -> AgentState:
    predictions = state.get("predictions", [])
    high_risk = [p for p in predictions if p.get("risk_level") == "high"]
    query = state.get("query", "")
    graph_summary = state.get("graph_summary", {})
    news_signals = state.get("news_signals", [])
    temporal_trends = state.get("temporal_trends", [])
    network_risk = state.get("network_risk", [])
    graph_insights = state.get("graph_insights", {})

    abnormal_suppliers = graph_insights.get("abnormal_suppliers", [])
    negative_news_count = sum(1 for s in news_signals if s.get("sentiment") == "negative")

    if high_risk:
        msg = f"Detected {len(high_risk)} high-risk companies from ML predictions."
    else:
        msg = "No high-risk companies detected in current batch."

    contagion = sorted(network_risk, key=lambda x: float(x.get("network_exposure_score", 0.0)), reverse=True)
    if contagion:
        top = contagion[0]
        msg += (
            f" {top.get('company_id')} has network exposure {float(top.get('network_exposure_score', 0.0)):.3f} "
            f"with dependency chain {top.get('dependency_chain', top.get('company_id'))}."
        )

    increasing = [t for t in temporal_trends if t.get("risk_trend") == "increasing"]
    if increasing:
        top = sorted(increasing, key=lambda x: float(x.get("risk_velocity", 0.0)), reverse=True)[0]
        msg += (
            f" {top.get('company_id')} risk is increasing with velocity {float(top.get('risk_velocity', 0.0)):.3f} "
            f"and acceleration {float(top.get('risk_acceleration', 0.0)):.3f}."
        )

    if abnormal_suppliers:
        top = abnormal_suppliers[0]
        msg += f" Top abnormal supplier is {top.get('supplier_id')} with anomaly score {top.get('avg_anomaly_score', 0):.3f}."

    if negative_news_count:
        msg += f" Negative sentiment appears in {negative_news_count} news items."

    if graph_summary.get("dry_run"):
        msg += " Graph layer is in dry-run mode due to missing Neo4j connectivity."

    state["answer"] = f"Query: {query}. Insight: {msg}"
    return state


def _llm_enhance_answer(state: AgentState) -> AgentState:
    settings = get_settings()
    if not settings.groq_api_key or ChatGroq is None:
        return state

    try:
        llm = ChatGroq(api_key=settings.groq_api_key, model=settings.groq_model, temperature=0.1)
        prompt = (
            "You are a financial intelligence agent. Provide concise risk insight and suggested actions.\n"
            "You must combine graph observations, ML risk predictions, and news sentiment signals.\n"
            f"User query: {state.get('query', '')}\n"
            f"Predictions: {state.get('predictions', [])}\n"
            f"Temporal trends: {state.get('temporal_trends', [])}\n"
            f"Network contagion: {state.get('network_risk', [])}\n"
            f"Graph insights: {state.get('graph_insights', {})}\n"
            f"News signals: {state.get('news_signals', [])}\n"
            f"Graph summary: {state.get('graph_summary', {})}\n"
            f"Current draft answer: {state.get('answer', '')}\n"
        )
        response = llm.invoke(prompt)
        content = getattr(response, "content", None)
        if isinstance(content, str) and content.strip():
            state["answer"] = content
    except Exception as exc:  # pragma: no cover
        LOGGER.warning("LLM enhance failed, using fallback answer: %s", exc)
        state["answer"] = _llm_failure_fallback_answer(state)

    return state


def _generate_alerts(state: AgentState) -> AgentState:
    alerts: list[dict[str, Any]] = []
    for row in state.get("predictions", []):
        trend_row = next(
            (t for t in state.get("temporal_trends", []) if t.get("company_id") == row.get("company_id")),
            {},
        )
        network_row = next(
            (n for n in state.get("network_risk", []) if n.get("company_id") == row.get("company_id")),
            {},
        )
        if row.get("risk_level") == "high":
            alerts.append(
                {
                    "alert_type": "company_risk",
                    "company_id": row.get("company_id"),
                    "severity": "critical",
                    "message": "High composite risk from transactions, news, and graph features.",
                    "evidence": {"risk_score": row.get("risk_score")},
                    "trend": trend_row.get("risk_trend", "stable"),
                    "network_risk": float(network_row.get("network_exposure_score", 0.0) or 0.0),
                    "exposed_companies": network_row.get("exposed_companies", []),
                    "dependency_chain": network_row.get("dependency_chain", row.get("company_id")),
                    "recommendation": "Escalate for immediate financial controls and supplier payment review.",
                }
            )
        elif row.get("risk_level") == "medium":
            alerts.append(
                {
                    "alert_type": "company_risk",
                    "company_id": row.get("company_id"),
                    "severity": "warning",
                    "message": "Medium risk detected. Review recent anomalies and event links.",
                    "evidence": {"risk_score": row.get("risk_score")},
                    "trend": trend_row.get("risk_trend", "stable"),
                    "network_risk": float(network_row.get("network_exposure_score", 0.0) or 0.0),
                    "exposed_companies": network_row.get("exposed_companies", []),
                    "dependency_chain": network_row.get("dependency_chain", row.get("company_id")),
                    "recommendation": "Schedule analyst review and monitor 24h transaction velocity.",
                }
            )

    for supplier in state.get("graph_insights", {}).get("abnormal_suppliers", []):
        alerts.append(
            {
                "alert_type": "supplier_anomaly",
                "supplier_id": supplier.get("supplier_id"),
                "severity": "warning",
                "message": "Supplier shows abnormal transaction behavior.",
                "evidence": supplier,
                "trend": "increasing",
                "recommendation": "Review linked company transactions and confirm invoice authenticity.",
            }
        )

    for event in state.get("graph_insights", {}).get("negative_events", []):
        alerts.append(
            {
                "alert_type": "negative_event",
                "company_id": event.get("company_id"),
                "severity": "warning",
                "message": "Negative news event may impact suppliers or cash flow.",
                "evidence": event,
                "trend": "increasing",
                "recommendation": "Reassess counterparty exposure and supplier concentration.",
            }
        )

    state["alerts"] = alerts
    return state


def _collect_graph_insights(state: AgentState) -> AgentState:
    state["graph_insights"] = _query_neo4j_insights()
    return state


def build_agent_workflow():
    if StateGraph is None:
        return None
    graph = StateGraph(AgentState)
    graph.add_node("collect_graph_insights", _collect_graph_insights)
    graph.add_node("rule_based_answer", _rule_based_answer)
    graph.add_node("llm_enhance_answer", _llm_enhance_answer)
    graph.add_node("generate_alerts", _generate_alerts)
    graph.add_edge(START, "collect_graph_insights")
    graph.add_edge("collect_graph_insights", "rule_based_answer")
    graph.add_edge("rule_based_answer", "llm_enhance_answer")
    graph.add_edge("llm_enhance_answer", "generate_alerts")
    graph.add_edge("generate_alerts", END)
    return graph.compile()


def run_agent(
    query: str,
    predictions: list[dict[str, Any]],
    graph_summary: dict[str, Any],
    news_signals: list[dict[str, Any]] | None = None,
    temporal_trends: list[dict[str, Any]] | None = None,
    network_risk: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    workflow = build_agent_workflow()
    state: AgentState = {
        "query": query,
        "predictions": predictions,
        "graph_summary": graph_summary,
        "news_signals": news_signals or [],
        "temporal_trends": temporal_trends or [],
        "network_risk": network_risk or [],
    }

    if workflow is None:
        state = _collect_graph_insights(state)
        state = _rule_based_answer(state)
        state = _generate_alerts(state)
        return {
            "answer": state.get("answer", ""),
            "alerts": state.get("alerts", []),
            "graph_insights": state.get("graph_insights", {}),
        }

    result = workflow.invoke(state)
    return {
        "answer": result.get("answer", ""),
        "alerts": result.get("alerts", []),
        "graph_insights": result.get("graph_insights", {}),
    }
