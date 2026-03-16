from __future__ import annotations

import logging
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

LOGGER = logging.getLogger(__name__)

FEATURES = [
    "transaction_volume",
    "avg_transaction_amount",
    "supplier_concentration",
    "abnormal_transaction_frequency",
    "avg_anomaly_score",
    "company_degree_centrality",
    "company_betweenness_centrality",
    "event_exposure_score",
    "negative_sentiment_ratio",
    "unique_suppliers",
    "risk_velocity",
    "anomaly_rate_7d",
    "sentiment_trend",
    "event_impact_score",
    "network_exposure_score",
    "systemic_importance_score",
]


def _default_model_path() -> Path:
    return Path(__file__).resolve().parents[1] / "models" / "risk_random_forest.joblib"


def _build_proxy_target(frame: pd.DataFrame) -> pd.Series:
    score = (
        0.25 * frame["abnormal_transaction_frequency"]
        + 0.20 * frame["avg_anomaly_score"]
        + 0.10 * frame["supplier_concentration"]
        + 0.10 * frame["event_exposure_score"]
        + 0.10 * frame["negative_sentiment_ratio"]
        + 0.10 * frame["anomaly_rate_7d"]
        + 0.10 * frame["risk_velocity"].clip(lower=0)
        + 0.05 * (-frame["sentiment_trend"])
        + 0.06 * frame["network_exposure_score"]
        + 0.04 * frame["systemic_importance_score"]
    )
    q1 = float(score.quantile(0.4))
    q2 = float(score.quantile(0.75))
    labels = pd.Series(0, index=frame.index)
    labels[score >= q1] = 1
    labels[score >= q2] = 2
    return labels


def _load_or_train_model(frame: pd.DataFrame, model_path: Path | None = None) -> RandomForestClassifier:
    target_path = model_path or _default_model_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        LOGGER.info("Loading risk model from %s", target_path)
        model: RandomForestClassifier = joblib.load(target_path)
        model_features = list(getattr(model, "feature_names_in_", []))
        if model_features and model_features != FEATURES:
            LOGGER.info("Detected feature schema change. Retraining risk model with updated features.")
        else:
            return model

    LOGGER.info("Training RandomForest risk model and persisting to %s", target_path)
    y = _build_proxy_target(frame)
    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        random_state=42,
        class_weight="balanced_subsample",
    )
    model.fit(frame[FEATURES], y)
    joblib.dump(model, target_path)
    return model


def predict_risk(graph_and_transaction_features_df: pd.DataFrame, model_path: str | None = None) -> pd.DataFrame:
    """Input: graph + transaction features. Output: risk predictions."""
    if graph_and_transaction_features_df.empty:
        return pd.DataFrame(columns=["company_id", "risk_score", "risk_level"])

    frame = graph_and_transaction_features_df.copy()
    for col in FEATURES:
        frame[col] = pd.to_numeric(frame.get(col, 0.0), errors="coerce").fillna(0.0)

    model = _load_or_train_model(frame, Path(model_path) if model_path else None)
    proba = model.predict_proba(frame[FEATURES])

    # Use highest non-low class probability as operational risk score.
    if proba.shape[1] >= 3:
        risk_score = pd.Series(proba[:, 2] + (0.5 * proba[:, 1]), index=frame.index).clip(0.0, 1.0)
    elif proba.shape[1] == 2:
        risk_score = pd.Series(proba[:, 1], index=frame.index).clip(0.0, 1.0)
    else:
        risk_score = pd.Series([0.0] * len(frame), index=frame.index)

    base_ml = risk_score
    network_component = pd.to_numeric(frame.get("network_exposure_score", 0.0), errors="coerce").fillna(0.0)
    systemic_component = pd.to_numeric(frame.get("systemic_importance_score", 0.0), errors="coerce").fillna(0.0)
    frame["risk_score"] = (0.75 * base_ml + 0.15 * network_component + 0.10 * systemic_component).clip(0.0, 1.0)
    frame["propagated_risk"] = frame["risk_score"]
    frame["systemic_risk_level"] = pd.cut(
        frame["risk_score"],
        bins=[-0.001, 0.40, 0.75, 1.0],
        labels=["low", "medium", "high"],
    ).astype(str)
    frame["risk_level"] = frame["systemic_risk_level"]

    return frame[["company_id", "risk_score", "propagated_risk", "systemic_risk_level", "risk_level"]]
