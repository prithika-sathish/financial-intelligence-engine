from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)

SENTIMENT_TO_SCORE = {"negative": -1.0, "neutral": 0.0, "positive": 1.0}


def _rolling_company_features(merged_tx: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for company_id, group in merged_tx.groupby("company_id", dropna=False):
        grp = group.sort_values("timestamp").set_index("timestamp")
        if grp.empty:
            continue
        tx_count_24h = grp["transaction_id"].rolling("24h").count().iloc[-1]
        tx_count_7d = grp["transaction_id"].rolling("7D").count().iloc[-1]
        avg_amt_24h = grp["amount"].rolling("24h").mean().iloc[-1]
        avg_amt_7d = grp["amount"].rolling("7D").mean().iloc[-1]
        anomaly_rate_24h = grp["anomaly_flag"].rolling("24h").mean().iloc[-1]
        anomaly_rate_7d = grp["anomaly_flag"].rolling("7D").mean().iloc[-1]

        rows.append(
            {
                "company_id": company_id,
                "transaction_count_24h": float(np.nan_to_num(tx_count_24h, nan=0.0)),
                "transaction_count_7d": float(np.nan_to_num(tx_count_7d, nan=0.0)),
                "avg_transaction_amount_24h": float(np.nan_to_num(avg_amt_24h, nan=0.0)),
                "avg_transaction_amount_7d": float(np.nan_to_num(avg_amt_7d, nan=0.0)),
                "anomaly_rate_24h": float(np.nan_to_num(anomaly_rate_24h, nan=0.0)),
                "anomaly_rate_7d": float(np.nan_to_num(anomaly_rate_7d, nan=0.0)),
            }
        )
    return pd.DataFrame(rows)


def _build_risk_series(
    company_id: str,
    merged_tx: pd.DataFrame,
    sentiment_df: pd.DataFrame,
    events_df: pd.DataFrame,
) -> pd.Series:
    tx = merged_tx[merged_tx["company_id"] == company_id].copy()
    if tx.empty:
        return pd.Series(dtype=float)

    tx_daily = tx.set_index("timestamp").sort_index()
    anomaly_daily = tx_daily["anomaly_score"].resample("1D").mean().fillna(0.0)

    if sentiment_df.empty:
        sentiment_daily = pd.Series(0.0, index=anomaly_daily.index)
    else:
        sent = sentiment_df[sentiment_df["company_id"] == company_id].copy()
        if sent.empty:
            sentiment_daily = pd.Series(0.0, index=anomaly_daily.index)
        else:
            sent["sentiment_score"] = sent["sentiment"].map(SENTIMENT_TO_SCORE).fillna(0.0)
            sent["published_at"] = pd.to_datetime(sent["published_at"], utc=True, errors="coerce")
            sentiment_daily = (
                sent.set_index("published_at")["sentiment_score"].resample("1D").mean().reindex(anomaly_daily.index, fill_value=0.0)
            )

    if events_df.empty:
        event_daily = pd.Series(0.0, index=anomaly_daily.index)
    else:
        evt = events_df[events_df["linked_entity_id"] == company_id].copy()
        if evt.empty:
            event_daily = pd.Series(0.0, index=anomaly_daily.index)
        else:
            evt["event_timestamp"] = pd.to_datetime(evt["event_timestamp"], utc=True, errors="coerce")
            event_daily = (
                evt.set_index("event_timestamp")
                .resample("1D")["event_impact_score"]
                .sum()
                .reindex(anomaly_daily.index, fill_value=0.0)
            )

    event_norm = event_daily / max(event_daily.max(), 1.0)
    risk_series = (0.55 * anomaly_daily) + (0.25 * (-sentiment_daily)) + (0.20 * event_norm)
    return risk_series.fillna(0.0)


def _trend_stats(risk_series: pd.Series) -> tuple[str, float, float]:
    if risk_series.empty:
        return "stable", 0.0, 0.0
    y = risk_series.values.astype(float)
    x = np.arange(len(y), dtype=float)
    if len(y) == 1:
        return "stable", 0.0, 0.0

    slope = float(np.polyfit(x, y, 1)[0])
    if len(y) >= 3:
        quad = np.polyfit(x, y, 2)
        acceleration = float(2.0 * quad[0])
    else:
        acceleration = 0.0

    if slope > 0.01:
        trend = "increasing"
    elif slope < -0.01:
        trend = "decreasing"
    else:
        trend = "stable"
    return trend, slope, acceleration


def analyze_temporal_risk(
    transactions_df: pd.DataFrame,
    anomaly_scores_df: pd.DataFrame,
    sentiment_df: pd.DataFrame,
    events_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute temporal features and trend metrics per company."""
    if transactions_df.empty:
        temporal_cols = [
            "company_id",
            "transaction_count_24h",
            "transaction_count_7d",
            "avg_transaction_amount_24h",
            "avg_transaction_amount_7d",
            "anomaly_rate_24h",
            "anomaly_rate_7d",
            "sentiment_trend",
            "event_impact_score",
        ]
        trend_cols = ["company_id", "risk_trend", "risk_velocity", "risk_acceleration"]
        return pd.DataFrame(columns=temporal_cols), pd.DataFrame(columns=trend_cols)

    tx = transactions_df.copy()
    tx["timestamp"] = pd.to_datetime(tx["timestamp"], utc=True, errors="coerce")
    tx["amount"] = pd.to_numeric(tx.get("amount", 0.0), errors="coerce").fillna(0.0)
    merged = tx.merge(anomaly_scores_df, on="transaction_id", how="left")
    merged["anomaly_score"] = pd.to_numeric(merged.get("anomaly_score", 0.0), errors="coerce").fillna(0.0)
    merged["anomaly_flag"] = pd.to_numeric(merged.get("anomaly_flag", 0), errors="coerce").fillna(0).astype(int)

    temporal_df = _rolling_company_features(merged)

    # sentiment_trend and event_impact_score as temporal model inputs.
    sent = sentiment_df.copy() if not sentiment_df.empty else pd.DataFrame(columns=["company_id", "sentiment"])
    if not sent.empty:
        sent["sentiment_score"] = sent["sentiment"].map(SENTIMENT_TO_SCORE).fillna(0.0)
        sent_agg = sent.groupby("company_id", dropna=False)["sentiment_score"].mean().reset_index().rename(
            columns={"sentiment_score": "sentiment_trend"}
        )
    else:
        sent_agg = pd.DataFrame(columns=["company_id", "sentiment_trend"])

    if not events_df.empty:
        evt_agg = (
            events_df.groupby("linked_entity_id", dropna=False)["event_impact_score"]
            .sum()
            .reset_index()
            .rename(columns={"linked_entity_id": "company_id"})
        )
    else:
        evt_agg = pd.DataFrame(columns=["company_id", "event_impact_score"])

    temporal_df = temporal_df.merge(sent_agg, on="company_id", how="left")
    temporal_df = temporal_df.merge(evt_agg, on="company_id", how="left")
    temporal_df["sentiment_trend"] = pd.to_numeric(temporal_df["sentiment_trend"], errors="coerce").fillna(0.0)
    temporal_df["event_impact_score"] = pd.to_numeric(temporal_df["event_impact_score"], errors="coerce").fillna(0.0)

    trend_rows: list[dict[str, Any]] = []
    for company_id in temporal_df["company_id"].dropna().unique().tolist():
        series = _build_risk_series(company_id, merged, sentiment_df, events_df)
        trend, velocity, accel = _trend_stats(series)
        trend_rows.append(
            {
                "company_id": company_id,
                "risk_trend": trend,
                "risk_velocity": float(velocity),
                "risk_acceleration": float(accel),
                "risk_history": str([round(float(v), 6) for v in series.tail(14).tolist()]),
            }
        )

    trend_df = pd.DataFrame(trend_rows)
    LOGGER.info("Temporal analysis complete for %s companies", len(trend_df))
    return temporal_df, trend_df
