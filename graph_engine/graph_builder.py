from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from graph_engine.neo4j_client import neo4j_session

LOGGER = logging.getLogger(__name__)

MERGE_QUERY = """
MERGE (c:Company {company_id: $company_id})
SET c.risk_history = coalesce(c.risk_history, '[]')
MERGE (s:Supplier {supplier_id: $supplier_id})
MERGE (a:Account {account_id: $account_id})
MERGE (t:Transaction {transaction_id: $transaction_id})
SET t.amount = $amount,
    t.currency = $currency,
    t.timestamp = $timestamp,
    t.description = $description,
    t.anomaly_score = $anomaly_score,
    t.anomaly_flag = $anomaly_flag
MERGE (c)-[:COMPANY_PAYS_SUPPLIER]->(s)
MERGE (a)-[:ACCOUNT_EXECUTES_TRANSACTION]->(t)
MERGE (c)-[:OWNS_ACCOUNT]->(a)
"""

EVENT_QUERY = """
MERGE (e:Event {event_id: $event_id})
SET e.event_type = $event_type,
    e.trigger = $trigger,
    e.sentiment = $sentiment,
    e.news_id = $news_id,
    e.timestamp = $event_timestamp,
    e.impact_score = $event_impact_score,
    e.decay_factor = $event_decay_factor
WITH e
MATCH (c:Company {company_id: $company_id})
MERGE (c)-[:COMPANY_AFFECTED_BY_EVENT]->(e)
MERGE (e)-[r:IMPACTS]->(c)
SET r.impact_score = $event_impact_score,
    r.decay_factor = $event_decay_factor
"""


ENTITY_QUERY = """
MERGE (en:Entity {entity_id: $entity_id})
SET en.name = $entity_name, en.entity_type = $entity_type, en.news_id = $news_id
"""


def _safe_run(session: object, query: str, params: dict[str, Any]) -> bool:
    """Execute a query on session. Fails fast without retries.
    
    Returns True if successful, False otherwise (logs only once via caller).
    """
    try:
        session.run(query, params)
        return True
    except Exception:  # pragma: no cover
        # Fail fast: don't log here, let caller handle logging once per stage
        return False


def build_financial_graph(
    transactions_df: pd.DataFrame,
    entities_df: pd.DataFrame,
    events_df: pd.DataFrame,
    risk_trends_df: pd.DataFrame | None = None,
    risk_predictions_df: pd.DataFrame | None = None,
    dependency_edges_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Input: entities + transactions. Output: Neo4j graph write summary."""
    tx_rows = transactions_df.to_dict(orient="records") if not transactions_df.empty else []
    event_rows = events_df.to_dict(orient="records") if not events_df.empty else []
    entity_rows = entities_df.to_dict(orient="records") if not entities_df.empty else []
    writes = {
        "transactions": 0,
        "events": 0,
        "entities": 0,
        "company_updates": 0,
        "dependency_edges": 0,
        "dry_run": False,
    }

    with neo4j_session() as session:
        if session is None:
            writes["dry_run"] = True
            writes["transactions"] = len(tx_rows)
            writes["events"] = len(event_rows)
            writes["entities"] = len(entity_rows)
            return writes

        for row in tx_rows:
            params = {
                "company_id": row.get("company_id", "UNKNOWN_COMPANY"),
                "supplier_id": row.get("supplier_id", "UNKNOWN_SUPPLIER"),
                "account_id": row.get("account_id", "UNKNOWN_ACCOUNT"),
                "transaction_id": row.get("transaction_id", "UNKNOWN_TX"),
                "amount": float(row.get("amount", 0.0) or 0.0),
                "currency": row.get("currency", "USD"),
                "timestamp": str(row.get("timestamp", "")),
                "description": row.get("description", ""),
                "anomaly_score": float(row.get("anomaly_score", 0.0) or 0.0),
                "anomaly_flag": int(row.get("anomaly_flag", 0) or 0),
            }
            if _safe_run(session, MERGE_QUERY, params):
                writes["transactions"] += 1

        for event in event_rows:
            params = {
                "company_id": event.get("linked_entity_id", "UNKNOWN_COMPANY"),
                "event_id": event.get("event_id", "UNKNOWN_EVENT"),
                "event_type": event.get("event_type", "UNKNOWN_EVENT"),
                "trigger": event.get("trigger", ""),
                "sentiment": event.get("sentiment", "neutral"),
                "news_id": event.get("news_id", "UNKNOWN_NEWS"),
                "event_timestamp": str(event.get("event_timestamp", "")),
                "event_impact_score": float(event.get("event_impact_score", 0.0) or 0.0),
                "event_decay_factor": float(event.get("event_decay_factor", 1.0) or 1.0),
            }
            if _safe_run(session, EVENT_QUERY, params):
                writes["events"] += 1

        for entity in entity_rows:
            params = {
                "entity_id": entity.get("entity_id", "UNKNOWN_ENTITY"),
                "entity_name": entity.get("entity_name", "UNKNOWN"),
                "entity_type": entity.get("entity_type", "Entity"),
                "news_id": entity.get("news_id", "UNKNOWN_NEWS"),
            }
            if _safe_run(session, ENTITY_QUERY, params):
                writes["entities"] += 1

        if risk_trends_df is not None and not risk_trends_df.empty:
            for row in risk_trends_df.to_dict(orient="records"):
                if _safe_run(
                    session,
                    """
                    MERGE (c:Company {company_id: $company_id})
                    SET c.risk_history = $risk_history,
                        c.risk_trend = $risk_trend,
                        c.risk_velocity = $risk_velocity,
                        c.risk_acceleration = $risk_acceleration
                    """,
                    {
                        "company_id": row.get("company_id", "UNKNOWN_COMPANY"),
                        "risk_history": str(row.get("risk_history", "[]")),
                        "risk_trend": row.get("risk_trend", "stable"),
                        "risk_velocity": float(row.get("risk_velocity", 0.0) or 0.0),
                        "risk_acceleration": float(row.get("risk_acceleration", 0.0) or 0.0),
                    },
                ):
                    writes["company_updates"] += 1

        if risk_predictions_df is not None and not risk_predictions_df.empty:
            for row in risk_predictions_df.to_dict(orient="records"):
                if _safe_run(
                    session,
                    """
                    MERGE (c:Company {company_id: $company_id})
                    SET c.base_risk = $base_risk,
                        c.propagated_risk = $propagated_risk,
                        c.systemic_importance = $systemic_importance
                    """,
                    {
                        "company_id": row.get("company_id", "UNKNOWN_COMPANY"),
                        "base_risk": float(row.get("risk_score", 0.0) or 0.0),
                        "propagated_risk": float(row.get("propagated_risk", row.get("risk_score", 0.0)) or 0.0),
                        "systemic_importance": float(row.get("systemic_importance_score", 0.0) or 0.0),
                    },
                ):
                    writes["company_updates"] += 1

        if dependency_edges_df is not None and not dependency_edges_df.empty:
            for row in dependency_edges_df.to_dict(orient="records"):
                if _safe_run(
                    session,
                    """
                    MERGE (a:Company {company_id: $from_company_id})
                    MERGE (b:Company {company_id: $to_company_id})
                    MERGE (a)-[r:DEPENDS_ON]->(b)
                    SET r.weight = $weight
                    """,
                    {
                        "from_company_id": row.get("from_company_id", "UNKNOWN_COMPANY"),
                        "to_company_id": row.get("to_company_id", "UNKNOWN_COMPANY"),
                        "weight": float(row.get("weight", 0.0) or 0.0),
                    },
                ):
                    writes["dependency_edges"] += 1

    LOGGER.info(
        "Graph build complete | tx=%s events=%s entities=%s dry_run=%s",
        writes["transactions"],
        writes["events"],
        writes["entities"],
        writes["dry_run"],
    )

    return writes
