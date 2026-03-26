from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd

from agent_system.graph_agent import run_agent
from data_ingestion.loader import load_news, load_transactions
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
from configs.logging_config import configure_logging

configure_logging()
LOGGER = logging.getLogger("pipeline")


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


def _setup_pipeline_file_logging(root: Path) -> None:
    logs_dir = root / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_path = (logs_dir / "pipeline.log").resolve()

    for handler in LOGGER.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename).resolve() == log_path:
            return

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    LOGGER.addHandler(file_handler)


def _compute_and_save_metrics(output_dir: Path) -> dict:
    anomaly_path = output_dir / "anomaly_scores.csv"
    predictions_path = output_dir / "risk_predictions.csv"

    anomalies_df = pd.read_csv(anomaly_path) if anomaly_path.exists() else pd.DataFrame()
    predictions_df = pd.read_csv(predictions_path) if predictions_path.exists() else pd.DataFrame()

    total_transactions = int(len(anomalies_df))
    anomaly_count = int(pd.to_numeric(anomalies_df.get("anomaly_flag", 0), errors="coerce").fillna(0).sum())
    anomaly_pct = (100.0 * anomaly_count / total_transactions) if total_transactions else 0.0

    risk_col = "propagated_risk" if "propagated_risk" in predictions_df.columns else "risk_score"
    if risk_col not in predictions_df.columns:
        predictions_df[risk_col] = 0.0
    predictions_df[risk_col] = pd.to_numeric(predictions_df[risk_col], errors="coerce").fillna(0.0)

    average_risk_score = float(predictions_df[risk_col].mean()) if not predictions_df.empty else 0.0
    top_risky_companies = []
    if not predictions_df.empty and "company_id" in predictions_df.columns:
        top_rows = predictions_df.sort_values(risk_col, ascending=False).head(5)
        top_risky_companies = [
            {
                "company_id": row.get("company_id"),
                "risk_score": float(row.get(risk_col, 0.0) or 0.0),
            }
            for row in top_rows.to_dict(orient="records")
        ]

    payload = {
        "total_transactions": total_transactions,
        "anomalies_detected": {
            "count": anomaly_count,
            "percentage": round(anomaly_pct, 2),
        },
        "average_risk_score": round(average_risk_score, 6),
        "top_risky_companies": top_risky_companies,
    }

    with (output_dir / "metrics.json").open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    return payload


def _read_json(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def run_pipeline() -> dict:
    root = Path(__file__).resolve().parent
    sample_dir = root / "sample_data"
    _setup_pipeline_file_logging(root)
    pipeline_started = time.perf_counter()
    LOGGER.info("Pipeline run started")

    stage_started = time.perf_counter()
    LOGGER.info("Stage 1/11 start: loading sample data")
    tx_records = _read_json(sample_dir / "sample_transactions.json")
    news_records = _read_json(sample_dir / "sample_news.json")
    tx_df = load_transactions(tx_records)
    news_df = load_news(news_records)
    LOGGER.info(
        "Stage 1/11 end: loaded data | tx_records=%s news_records=%s duration_sec=%.3f",
        len(tx_df),
        len(news_df),
        time.perf_counter() - stage_started,
    )

    stage_started = time.perf_counter()
    LOGGER.info("Stage 2/11 start: transaction anomaly detection")
    anomaly_scores_df = detect_transaction_anomalies(tx_df)
    LOGGER.info(
        "Stage 2/11 end: anomaly detection complete | records=%s duration_sec=%.3f",
        len(anomaly_scores_df),
        time.perf_counter() - stage_started,
    )

    stage_started = time.perf_counter()
    LOGGER.info("Stage 3/11 start: FinBERT sentiment and entity/event extraction")
    entities_df, events_df, sentiment_df = analyze_news_dataframe(news_df)
    LOGGER.info(
        "Stage 3/11 end: news analysis complete | entities=%s events=%s sentiments=%s duration_sec=%.3f",
        len(entities_df),
        len(events_df),
        len(sentiment_df),
        time.perf_counter() - stage_started,
    )

    stage_started = time.perf_counter()
    LOGGER.info("Stage 4/11 start: knowledge graph construction")
    
    # Initialize tx_graph_df before Neo4j check to avoid UnboundLocalError in Stage 8
    tx_graph_df = tx_df.merge(anomaly_scores_df, on="transaction_id", how="left")
    
    # Check Neo4j connectivity BEFORE attempting writes
    if not is_neo4j_available():
        LOGGER.info("Stage 4/11 skipped: Neo4j unavailable")
        graph_summary = {"transactions": 0, "events": 0, "entities": 0, "dry_run": True}
    else:
        graph_summary = build_financial_graph(
            transactions_df=tx_graph_df,
            entities_df=entities_df,
            events_df=events_df,
        )
        LOGGER.info(
            "Stage 4/11 end: graph construction complete | tx_rows=%s summary=%s duration_sec=%.3f",
            len(tx_graph_df),
            graph_summary,
            time.perf_counter() - stage_started,
        )

    stage_started = time.perf_counter()
    LOGGER.info("Stage 5/11 start: temporal analysis")
    temporal_df, trend_df = analyze_temporal_risk(tx_df, anomaly_scores_df, sentiment_df, events_df)
    LOGGER.info(
        "Stage 5/11 end: temporal analysis complete | temporal=%s trends=%s duration_sec=%.3f",
        len(temporal_df),
        len(trend_df),
        time.perf_counter() - stage_started,
    )

    stage_started = time.perf_counter()
    LOGGER.info("Stage 6/11 start: graph feature extraction")
    features_df = build_graph_features(
        tx_df,
        anomaly_scores_df,
        entities_df,
        events_df,
        sentiment_df,
        temporal_df,
        trend_df,
    )
    LOGGER.info(
        "Stage 6/11 end: feature extraction complete | feature_rows=%s duration_sec=%.3f",
        len(features_df),
        time.perf_counter() - stage_started,
    )

    stage_started = time.perf_counter()
    LOGGER.info("Stage 7/11 start: risk prediction")
    predictions_df = predict_risk(features_df)
    LOGGER.info(
        "Stage 7/11 end: risk prediction complete | prediction_rows=%s duration_sec=%.3f",
        len(predictions_df),
        time.perf_counter() - stage_started,
    )

    stage_started = time.perf_counter()
    LOGGER.info("Stage 8/11 start: dependency propagation")
    network_df, dependency_edges_df = propagate_dependency_risk(predictions_df, tx_df, alpha=0.4, beta=0.3, max_iter=3)
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
    drop_cols = [c for c in ["propagated_risk_net"] if c in predictions_df.columns]
    if drop_cols:
        predictions_df = predictions_df.drop(columns=drop_cols)

    # Update graph with risk predictions only if Neo4j is available
    if is_neo4j_available():
        graph_summary = build_financial_graph(
            transactions_df=tx_graph_df,
            entities_df=entities_df,
            events_df=events_df,
            risk_trends_df=trend_df,
            risk_predictions_df=predictions_df,
            dependency_edges_df=dependency_edges_df,
        )
    else:
        LOGGER.info("Stage 8/11: Skipping graph update due to Neo4j unavailability")
        graph_summary = {"transactions": 0, "events": 0, "entities": 0, "dry_run": True}
    
    LOGGER.info(
        "Stage 8/11 end: dependency propagation complete | network_rows=%s dependency_edges=%s duration_sec=%.3f",
        len(network_df),
        len(dependency_edges_df),
        time.perf_counter() - stage_started,
    )

    stage_started = time.perf_counter()
    LOGGER.info("Stage 9/11 start: decision-support enrichment")
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
    LOGGER.info(
        "Stage 9/11 end: decision-support enrichment complete | prediction_rows=%s duration_sec=%.3f",
        len(predictions_df),
        time.perf_counter() - stage_started,
    )

    stage_started = time.perf_counter()
    LOGGER.info("Stage 10/11 start: agent reasoning")
    agent_result = run_agent(
        query="Which suppliers show abnormal financial behavior?",
        predictions=predictions_df.to_dict(orient="records"),
        graph_summary=graph_summary,
        news_signals=sentiment_df.to_dict(orient="records"),
        temporal_trends=trend_df.to_dict(orient="records"),
        network_risk=network_df.to_dict(orient="records"),
    )
    LOGGER.info(
        "Stage 10/11 end: agent reasoning complete | alerts=%s duration_sec=%.3f",
        len(agent_result.get("alerts", [])),
        time.perf_counter() - stage_started,
    )

    stage_started = time.perf_counter()
    LOGGER.info("Stage 11/11 start: persisting outputs")
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

    LOGGER.info(
        "Stage 11/11 end: outputs persisted | output_dir=%s duration_sec=%.3f",
        output_dir,
        time.perf_counter() - stage_started,
    )

    metrics = _compute_and_save_metrics(output_dir)
    LOGGER.info("Post-stage metrics saved | metrics=%s", metrics)
    LOGGER.info("Pipeline run completed | total_duration_sec=%.3f", time.perf_counter() - pipeline_started)

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
