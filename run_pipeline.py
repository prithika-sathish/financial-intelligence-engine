from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from agent_system.graph_agent import run_agent
from data_ingestion.loader import load_news, load_transactions
from graph_engine.graph_builder import build_financial_graph
from ml_models.dependency_propagation import propagate_dependency_risk
from ml_models.feature_extractor import build_graph_features
from ml_models.risk_model import predict_risk
from ml_models.temporal_analyzer import analyze_temporal_risk
from news_analysis.finbert_analyzer import analyze_news_dataframe
from transaction_analysis.anomaly_detector import detect_transaction_anomalies
from configs.logging_config import configure_logging

configure_logging()
LOGGER = logging.getLogger("pipeline")


def _read_json(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def run_pipeline() -> dict:
    root = Path(__file__).resolve().parent
    sample_dir = root / "sample_data"

    LOGGER.info("Stage 1/10: loading sample data")
    tx_records = _read_json(sample_dir / "sample_transactions.json")
    news_records = _read_json(sample_dir / "sample_news.json")
    tx_df = load_transactions(tx_records)
    news_df = load_news(news_records)

    LOGGER.info("Stage 2/10: transaction anomaly detection")
    anomaly_scores_df = detect_transaction_anomalies(tx_df)

    LOGGER.info("Stage 3/10: FinBERT sentiment and entity/event extraction")
    entities_df, events_df, sentiment_df = analyze_news_dataframe(news_df)

    LOGGER.info("Stage 4/10: knowledge graph construction")
    tx_graph_df = tx_df.merge(anomaly_scores_df, on="transaction_id", how="left")
    graph_summary = build_financial_graph(
        transactions_df=tx_graph_df,
        entities_df=entities_df,
        events_df=events_df,
    )

    LOGGER.info("Stage 5/10: temporal analysis")
    temporal_df, trend_df = analyze_temporal_risk(tx_df, anomaly_scores_df, sentiment_df, events_df)

    LOGGER.info("Stage 6/10: graph feature extraction")
    features_df = build_graph_features(
        tx_df,
        anomaly_scores_df,
        entities_df,
        events_df,
        sentiment_df,
        temporal_df,
        trend_df,
    )

    LOGGER.info("Stage 7/10: risk prediction")
    predictions_df = predict_risk(features_df)

    LOGGER.info("Stage 8/10: dependency propagation")
    network_df, dependency_edges_df = propagate_dependency_risk(predictions_df, tx_df, alpha=0.3, max_iter=8)
    predictions_df = predictions_df.merge(
        network_df[["company_id", "propagated_risk", "systemic_importance_score", "network_exposure_score"]],
        on="company_id",
        how="left",
        suffixes=("", "_net"),
    )
    predictions_df["propagated_risk"] = pd.to_numeric(
        predictions_df.get("propagated_risk_net", predictions_df.get("propagated_risk", predictions_df["risk_score"])),
        errors="coerce",
    ).fillna(predictions_df["risk_score"])
    predictions_df["systemic_importance_score"] = pd.to_numeric(
        predictions_df.get("systemic_importance_score", 0.0), errors="coerce"
    ).fillna(0.0)
    predictions_df["systemic_risk_level"] = pd.cut(
        predictions_df["propagated_risk"],
        bins=[-0.001, 0.40, 0.75, 1.0],
        labels=["low", "medium", "high"],
    ).astype(str)
    predictions_df["risk_level"] = predictions_df["systemic_risk_level"]
    drop_cols = [c for c in ["propagated_risk_net"] if c in predictions_df.columns]
    if drop_cols:
        predictions_df = predictions_df.drop(columns=drop_cols)

    graph_summary = build_financial_graph(
        transactions_df=tx_graph_df,
        entities_df=entities_df,
        events_df=events_df,
        risk_trends_df=trend_df,
        risk_predictions_df=predictions_df,
        dependency_edges_df=dependency_edges_df,
    )

    LOGGER.info("Stage 9/10: agent reasoning")
    agent_result = run_agent(
        query="Which suppliers show abnormal financial behavior?",
        predictions=predictions_df.to_dict(orient="records"),
        graph_summary=graph_summary,
        news_signals=sentiment_df.to_dict(orient="records"),
        temporal_trends=trend_df.to_dict(orient="records"),
        network_risk=network_df.to_dict(orient="records"),
    )

    LOGGER.info("Stage 10/10: persisting outputs")
    output_dir = root / "outputs"
    output_dir.mkdir(exist_ok=True)
    anomaly_scores_df.to_csv(output_dir / "anomaly_scores.csv", index=False)
    entities_df.to_csv(output_dir / "entities.csv", index=False)
    events_df.to_csv(output_dir / "events.csv", index=False)
    features_df.to_csv(output_dir / "features.csv", index=False)
    predictions_df.to_csv(output_dir / "risk_predictions.csv", index=False)
    trend_df.to_csv(output_dir / "risk_trends.csv", index=False)
    network_df.to_csv(output_dir / "network_risk_analysis.csv", index=False)

    merged = predictions_df.merge(trend_df, on="company_id", how="left")
    merged = merged.merge(features_df, on="company_id", how="left")
    risk_trends_payload = []
    for row in merged.to_dict(orient="records"):
        drivers = []
        if float(row.get("anomaly_rate_7d", 0.0) or 0.0) > 0.3:
            drivers.append("anomaly_rate_7d")
        if float(row.get("event_impact_score", 0.0) or 0.0) > 1.0:
            drivers.append("event_impact_score")
        if float(row.get("risk_velocity", 0.0) or 0.0) > 0.01:
            drivers.append("risk_velocity")
        if float(row.get("sentiment_trend", 0.0) or 0.0) < 0:
            drivers.append("negative_sentiment_trend")
        if not drivers:
            drivers = ["transaction_volume"]

        risk_trends_payload.append(
            {
                "company_id": row.get("company_id"),
                "risk_score": float(row.get("risk_score", 0.0) or 0.0),
                "risk_trend": row.get("risk_trend", "stable"),
                "risk_velocity": float(row.get("risk_velocity", 0.0) or 0.0),
                "top_risk_drivers": drivers,
            }
        )

    with (output_dir / "risk_trends.json").open("w", encoding="utf-8") as fh:
        json.dump(risk_trends_payload, fh, indent=2)

    network_payload = [
        {
            "company_id": row.get("company_id"),
            "base_risk": float(row.get("base_risk", 0.0) or 0.0),
            "propagated_risk": float(row.get("propagated_risk", 0.0) or 0.0),
            "network_exposure_score": float(row.get("network_exposure_score", 0.0) or 0.0),
            "systemic_importance_score": float(row.get("systemic_importance_score", 0.0) or 0.0),
        }
        for row in network_df.to_dict(orient="records")
    ]
    with (output_dir / "network_risk_analysis.json").open("w", encoding="utf-8") as fh:
        json.dump(network_payload, fh, indent=2)

    return {
        "graph_summary": graph_summary,
        "predictions": predictions_df.to_dict(orient="records"),
        "agent": agent_result,
        "output_dir": str(output_dir),
    }


if __name__ == "__main__":
    result = run_pipeline()
    LOGGER.info("Pipeline completed. Alerts generated: %s", len(result["agent"].get("alerts", [])))
    print(json.dumps(result, indent=2))
