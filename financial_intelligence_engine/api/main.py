from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel, Field

from agent_system.graph_agent import run_agent
from configs.logging_config import configure_logging
from data_ingestion.loader import load_news, load_transactions
from data_ingestion.schemas import IngestionResponse
from graph_engine.graph_builder import build_financial_graph
from graph_engine.neo4j_client import is_neo4j_available
from ml_models.dependency_propagation import propagate_dependency_risk
from ml_models.cost_impact_analyzer import add_cost_impact_and_criticality
from ml_models.decision_engine import recommend_actions
from ml_models.feature_extractor import build_graph_features
from ml_models.risk_model import predict_risk
from ml_models.simulation_engine import run_supplier_failure_simulations
from ml_models.temporal_analyzer import analyze_temporal_risk
from news_analysis.finbert_analyzer import analyze_news_dataframe
from transaction_analysis.anomaly_detector import detect_transaction_anomalies

app = FastAPI(title="Fin-IQ Financial Intelligence Engine", version="0.1.0")
configure_logging()
LOGGER = logging.getLogger(__name__)


def _normalize_series(values: pd.Series) -> pd.Series:
    x = pd.to_numeric(values, errors="coerce").fillna(0.0).astype(float).values
    return pd.Series((x - x.min()) / (x.max() - x.min() + 1e-8), index=values.index)


def _validate_risk_distribution(predictions_df: pd.DataFrame) -> None:
    try:
        assert float(predictions_df["risk_score"].std()) > 0.05
        assert float(predictions_df["propagated_risk"].std()) > 0.05
    except AssertionError:
        LOGGER.warning("Risk collapse detected")


def _validate_decision_support_outputs(predictions_df: pd.DataFrame) -> None:
    try:
        assert float(predictions_df["estimated_cost_impact"].std()) > 0.05
        assert int(predictions_df["recommended_action"].nunique()) >= 2
    except AssertionError:
        LOGGER.warning("Decision-support output collapse detected")

_STATE: dict[str, Any] = {
    "transactions_df": pd.DataFrame(),
    "news_df": pd.DataFrame(),
    "anomaly_scores_df": pd.DataFrame(),
    "entities_df": pd.DataFrame(),
    "events_df": pd.DataFrame(),
    "sentiment_df": pd.DataFrame(),
    "graph_summary": {},
    "temporal_df": pd.DataFrame(),
    "trend_df": pd.DataFrame(),
    "network_risk_df": pd.DataFrame(),
    "dependency_edges_df": pd.DataFrame(),
    "features_df": pd.DataFrame(),
    "predictions_df": pd.DataFrame(),
    "alerts": [],
}


class TransactionsIngestRequest(BaseModel):
    transactions: list[dict[str, Any]] = Field(default_factory=list)
    news: list[dict[str, Any]] = Field(default_factory=list)


class GraphBuildRequest(BaseModel):
    company_id: str = "UNKNOWN_COMPANY"


class AgentQueryRequest(BaseModel):
    query: str


@app.post("/ingest_transactions", response_model=IngestionResponse)
def ingest_transactions(req: TransactionsIngestRequest):
    LOGGER.info("Ingesting transactions and news")
    tx_df = load_transactions(req.transactions)
    news_df = load_news(req.news)
    _STATE["transactions_df"] = tx_df
    _STATE["news_df"] = news_df

    sample = tx_df.head(3).to_dict(orient="records")
    return IngestionResponse(
        rows_ingested=len(tx_df),
        normalized_columns=list(tx_df.columns),
        sample=sample,
    )


@app.post("/run_graph_builder")
def run_graph_builder(req: GraphBuildRequest):
    LOGGER.info("Running graph builder stage")
    tx_df: pd.DataFrame = _STATE["transactions_df"]
    news_df: pd.DataFrame = _STATE["news_df"]

    entities_df, events_df, sentiment_df = analyze_news_dataframe(news_df)
    anomaly_scores_df = detect_transaction_anomalies(tx_df)
    
    # Check Neo4j connectivity BEFORE attempting writes
    if not is_neo4j_available():
        LOGGER.info("Graph builder skipped: Neo4j unavailable")
        graph_summary = {"transactions": 0, "events": 0, "entities": 0, "dry_run": True}
    else:
        tx_graph_df = tx_df.merge(anomaly_scores_df, on="transaction_id", how="left")
        graph_summary = build_financial_graph(
            transactions_df=tx_graph_df,
            entities_df=entities_df,
            events_df=events_df,
        )

    _STATE["anomaly_scores_df"] = anomaly_scores_df
    _STATE["entities_df"] = entities_df
    _STATE["events_df"] = events_df
    _STATE["sentiment_df"] = sentiment_df
    _STATE["graph_summary"] = graph_summary
    _STATE["temporal_df"] = pd.DataFrame()
    _STATE["trend_df"] = pd.DataFrame()
    _STATE["network_risk_df"] = pd.DataFrame()
    _STATE["dependency_edges_df"] = pd.DataFrame()

    return {
        "entities": entities_df.to_dict(orient="records"),
        "events": events_df.to_dict(orient="records"),
        "sentiment": sentiment_df.to_dict(orient="records"),
        "anomalies": anomaly_scores_df.to_dict(orient="records"),
        "graph_summary": graph_summary,
    }


@app.post("/run_ml_analysis")
def run_ml_analysis():
    LOGGER.info("Running graph feature extraction and ML risk stage")
    tx_df: pd.DataFrame = _STATE["transactions_df"]
    anomaly_df: pd.DataFrame = _STATE["anomaly_scores_df"]
    entities_df: pd.DataFrame = _STATE["entities_df"]
    events_df: pd.DataFrame = _STATE["events_df"]
    sentiment_df: pd.DataFrame = _STATE["sentiment_df"]
    temporal_df, trend_df = analyze_temporal_risk(tx_df, anomaly_df, sentiment_df, events_df)

    features_df = build_graph_features(
        tx_df,
        anomaly_df,
        entities_df,
        events_df,
        sentiment_df,
        temporal_df,
        trend_df,
    )
    predictions_df = predict_risk(features_df)
    network_risk_df, dependency_edges_df = propagate_dependency_risk(predictions_df, tx_df, alpha=0.4, beta=0.3, max_iter=3)
    predictions_df = predictions_df.merge(
        network_risk_df[["company_id", "propagated_risk", "network_exposure_score", "systemic_importance_score"]],
        on="company_id",
        how="left",
        suffixes=("", "_net"),
    )
    predictions_df["propagated_risk"] = pd.to_numeric(
        predictions_df.get("propagated_risk_net", predictions_df.get("propagated_risk", predictions_df["risk_score"])),
        errors="coerce",
    ).fillna(predictions_df["risk_score"])

    predictions_df["risk_score"] = _normalize_series(predictions_df["risk_score"]).clip(0.0, 1.0)
    predictions_df["propagated_risk"] = _normalize_series(predictions_df["propagated_risk"]).clip(0.0, 1.0)

    low_thr = float(predictions_df["propagated_risk"].quantile(0.33))
    high_thr = float(predictions_df["propagated_risk"].quantile(0.66))

    def _bucket_risk(x: float) -> str:
        if x < low_thr:
            return "low"
        if x < high_thr:
            return "medium"
        return "high"

    predictions_df["systemic_importance_score"] = pd.to_numeric(
        predictions_df.get("systemic_importance_score", 0.0), errors="coerce"
    ).fillna(0.0)
    predictions_df["systemic_risk_level"] = predictions_df["propagated_risk"].apply(_bucket_risk)
    predictions_df["risk_level"] = predictions_df["systemic_risk_level"]

    _validate_risk_distribution(predictions_df)
    if "propagated_risk_net" in predictions_df.columns:
        predictions_df = predictions_df.drop(columns=["propagated_risk_net"])

    predictions_df = add_cost_impact_and_criticality(
        predictions_df=predictions_df,
        transactions_df=tx_df,
        dependency_edges_df=dependency_edges_df,
        risk_col="propagated_risk",
    )
    predictions_df = recommend_actions(
        predictions_df=predictions_df,
        risk_col="propagated_risk",
        cost_col="estimated_cost_impact",
    )
    predictions_df = run_supplier_failure_simulations(
        predictions_df=predictions_df,
        dependency_edges_df=dependency_edges_df,
        transactions_df=tx_df,
        top_k_alternatives=3,
    )
    _validate_decision_support_outputs(predictions_df)

    tx_graph_df = tx_df.merge(anomaly_df, on="transaction_id", how="left")
    
    # Check Neo4j connectivity BEFORE attempting writes
    if not is_neo4j_available():
        LOGGER.info("Graph construction skipped: Neo4j unavailable")
        _STATE["graph_summary"] = {"transactions": 0, "events": 0, "entities": 0, "dry_run": True}
    else:
        _STATE["graph_summary"] = build_financial_graph(
            transactions_df=tx_graph_df,
            entities_df=entities_df,
            events_df=events_df,
            risk_trends_df=trend_df,
            risk_predictions_df=predictions_df,
            dependency_edges_df=dependency_edges_df,
        )

    _STATE["temporal_df"] = temporal_df
    _STATE["trend_df"] = trend_df
    _STATE["network_risk_df"] = network_risk_df
    _STATE["dependency_edges_df"] = dependency_edges_df
    _STATE["features_df"] = features_df
    _STATE["predictions_df"] = predictions_df

    return {
        "features": features_df.to_dict(orient="records"),
        "temporal": temporal_df.to_dict(orient="records"),
        "trends": trend_df.to_dict(orient="records"),
        "network_risk": network_risk_df.to_dict(orient="records"),
        "predictions": predictions_df.to_dict(orient="records"),
    }


@app.post("/query_agent")
def query_agent(req: AgentQueryRequest):
    LOGGER.info("Running agent reasoning")
    predictions_df: pd.DataFrame = _STATE["predictions_df"]
    graph_summary: dict[str, Any] = _STATE["graph_summary"]
    sentiment_df: pd.DataFrame = _STATE["sentiment_df"]
    trend_df: pd.DataFrame = _STATE["trend_df"]
    network_risk_df: pd.DataFrame = _STATE["network_risk_df"]

    response = run_agent(
        query=req.query,
        predictions=predictions_df.to_dict(orient="records"),
        graph_summary=graph_summary,
        news_signals=sentiment_df.to_dict(orient="records"),
        temporal_trends=trend_df.to_dict(orient="records"),
        network_risk=network_risk_df.to_dict(orient="records"),
    )
    _STATE["alerts"] = response.get("alerts", [])
    return response


@app.get("/get_alerts")
def get_alerts():
    return {"alerts": _STATE.get("alerts", [])}
