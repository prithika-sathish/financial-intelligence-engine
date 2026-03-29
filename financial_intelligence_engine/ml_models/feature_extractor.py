from __future__ import annotations

import logging

import networkx as nx
import numpy as np
import pandas as pd

from ml_models.dependency_propagation import compute_network_vulnerability_features

LOGGER = logging.getLogger(__name__)


def _standardize_with_fallback(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Standardize numeric columns with sklearn when available, else use manual z-score."""
    if not cols:
        return df

    try:
        # Runtime import avoids hard failure in environments where SciPy DLLs are policy-blocked.
        from sklearn.preprocessing import StandardScaler  # type: ignore

        scaler = StandardScaler()
        df[cols] = scaler.fit_transform(df[cols])
    except Exception as exc:
        LOGGER.warning("StandardScaler unavailable, using numpy fallback standardization: %s", exc)
        means = df[cols].mean(axis=0)
        stds = df[cols].std(axis=0, ddof=0).replace(0.0, 1.0)
        df[cols] = (df[cols] - means) / stds

    df[cols] = df[cols].clip(-5.0, 5.0)
    return df


def _supplier_concentration(group: pd.DataFrame) -> float:
    if group.empty:
        return 0.0
    counts = group["supplier_id"].value_counts(normalize=True)
    return float((counts**2).sum())


def build_graph_features(
    transactions_df: pd.DataFrame,
    anomaly_scores_df: pd.DataFrame,
    entities_df: pd.DataFrame,
    events_df: pd.DataFrame,
    sentiment_df: pd.DataFrame,
    temporal_df: pd.DataFrame,
    trend_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build graph-derived and transaction-derived features for risk modeling.

    Features include:
    - transaction_volume
    - supplier_concentration
    - abnormal_transaction_frequency
    - company_degree_centrality
    - company_betweenness_centrality
    - event_exposure_score
    """
    if transactions_df.empty:
        return pd.DataFrame(
            columns=[
                "company_id",
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
                "transaction_count_24h",
                "transaction_count_7d",
                "avg_transaction_amount_24h",
                "avg_transaction_amount_7d",
                "anomaly_rate_24h",
                "anomaly_rate_7d",
                "risk_velocity",
                "risk_acceleration",
                "sentiment_trend",
                "network_exposure_score",
                "in_degree_risk",
                "supplier_dependency_score",
                "risk_cluster_score",
                "systemic_importance_score",
            ]
        )

    tx = transactions_df.copy()
    tx["amount"] = pd.to_numeric(tx.get("amount", 0.0), errors="coerce").fillna(0.0)
    merged = tx.merge(anomaly_scores_df, on="transaction_id", how="left")
    merged["anomaly_score"] = pd.to_numeric(merged.get("anomaly_score", 0.0), errors="coerce").fillna(0.0)
    merged["anomaly_flag"] = pd.to_numeric(merged.get("anomaly_flag", 0), errors="coerce").fillna(0).astype(int)

    by_company = merged.groupby("company_id", dropna=False)
    features = by_company.agg(
        transaction_volume=("amount", "sum"),
        avg_transaction_amount=("amount", "mean"),
        abnormal_transaction_frequency=("anomaly_flag", "mean"),
        avg_anomaly_score=("anomaly_score", "mean"),
        unique_suppliers=("supplier_id", "nunique"),
    ).reset_index()

    concentration = (
        by_company.apply(_supplier_concentration, include_groups=False)
        .rename("supplier_concentration")
        .reset_index()
    )
    features = features.merge(concentration, on="company_id", how="left")

    graph = nx.Graph()
    for row in tx.to_dict(orient="records"):
        company = f"company::{row.get('company_id', 'UNKNOWN_COMPANY')}"
        supplier = f"supplier::{row.get('supplier_id', 'UNKNOWN_SUPPLIER')}"
        account = f"account::{row.get('account_id', 'UNKNOWN_ACCOUNT')}"
        graph.add_edge(company, supplier)
        graph.add_edge(company, account)

    degree = nx.degree_centrality(graph) if len(graph.nodes) > 1 else {}
    between = nx.betweenness_centrality(graph, normalized=True) if len(graph.nodes) > 1 else {}

    features["company_degree_centrality"] = features["company_id"].map(
        lambda x: float(degree.get(f"company::{x}", 0.0))
    )
    features["company_betweenness_centrality"] = features["company_id"].map(
        lambda x: float(between.get(f"company::{x}", 0.0))
    )

    if events_df.empty:
        event_exposure = pd.DataFrame(columns=["company_id", "event_exposure_score"])
    else:
        evt = events_df.copy()
        evt["weight"] = evt["sentiment"].map({"negative": 1.0, "neutral": 0.3, "positive": 0.1}).fillna(0.2)
        event_exposure = (
            evt.groupby("linked_entity_id", dropna=False)["weight"].sum().reset_index().rename(
                columns={"linked_entity_id": "company_id", "weight": "event_exposure_score"}
            )
        )

    if sentiment_df.empty:
        sent_stats = pd.DataFrame(columns=["company_id", "negative_sentiment_ratio"])
    else:
        sent = sentiment_df.copy()
        sent["is_negative"] = (sent["sentiment"] == "negative").astype(float)
        sent_stats = (
            sent.groupby("company_id", dropna=False)["is_negative"].mean().reset_index().rename(
                columns={"is_negative": "negative_sentiment_ratio"}
            )
        )

    features = features.merge(event_exposure, on="company_id", how="left")
    features = features.merge(sent_stats, on="company_id", how="left")
    if not temporal_df.empty:
        features = features.merge(temporal_df, on="company_id", how="left")
    if not trend_df.empty:
        features = features.merge(trend_df, on="company_id", how="left")

    network_features_df = compute_network_vulnerability_features(transactions_df)
    if not network_features_df.empty:
        features = features.merge(network_features_df, on="company_id", how="left")
    features["event_exposure_score"] = pd.to_numeric(features["event_exposure_score"], errors="coerce").fillna(0.0)
    features["negative_sentiment_ratio"] = pd.to_numeric(features["negative_sentiment_ratio"], errors="coerce").fillna(0.0)
    features["supplier_concentration"] = pd.to_numeric(features["supplier_concentration"], errors="coerce").fillna(0.0)

    for col in [
        "transaction_count_24h",
        "transaction_count_7d",
        "avg_transaction_amount_24h",
        "avg_transaction_amount_7d",
        "anomaly_rate_24h",
        "anomaly_rate_7d",
        "risk_velocity",
        "risk_acceleration",
        "sentiment_trend",
        "network_exposure_score",
        "in_degree_risk",
        "supplier_dependency_score",
        "risk_cluster_score",
        "systemic_importance_score",
    ]:
        if col not in features.columns:
            features[col] = 0.0
        features[col] = pd.to_numeric(features[col], errors="coerce").fillna(0.0)

    numeric_cols = [c for c in features.select_dtypes(include=[np.number]).columns if c != "company_id"]
    features = _standardize_with_fallback(features, numeric_cols)

    if "risk_trend" not in features.columns:
        features["risk_trend"] = "stable"
    features["risk_trend"] = features["risk_trend"].fillna("stable")

    LOGGER.info("Graph feature extraction complete for %s companies", len(features))
    return features
