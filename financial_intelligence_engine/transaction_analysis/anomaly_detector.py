from __future__ import annotations

import logging
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

LOGGER = logging.getLogger(__name__)

FRAUD_FEATURES = [
    "TransactionAmt",
    "txn_count_1h",
    "txn_count_24h",
    "txn_count_7d",
    "avg_amt_1h",
    "avg_amt_24h",
    "avg_amt_7d",
    "max_amt_24h",
    "amount_zscore_24h",
    "velocity_risk",
    "is_night_txn",
]


def _candidate_model_paths() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[2]
    return [
        repo_root / "models" / "xgb_fraud_model.pkl",
        repo_root.parent / "agentic-ai-transaction-analysis" / "models" / "xgb_fraud_model.pkl",
    ]


def _normalize_input_schema(transactions_df: pd.DataFrame) -> pd.DataFrame:
    frame = transactions_df.copy()
    rename_map = {
        "amount": "TransactionAmt",
        "timestamp": "TransactionDT",
    }
    frame = frame.rename(columns=rename_map)

    if "customer_id" not in frame.columns:
        if "account_id" in frame.columns:
            frame["customer_id"] = frame["account_id"].astype(str)
        elif "company_id" in frame.columns:
            frame["customer_id"] = frame["company_id"].astype(str)
        else:
            frame["customer_id"] = "UNKNOWN_CUSTOMER"

    if "TransactionDT" not in frame.columns:
        frame["TransactionDT"] = pd.Timestamp.utcnow()

    frame["TransactionDT"] = pd.to_datetime(frame["TransactionDT"], utc=True, errors="coerce")
    frame["TransactionAmt"] = pd.to_numeric(frame["TransactionAmt"], errors="coerce").fillna(0.0)
    return frame


def _engineer_fraud_features(transactions_df: pd.DataFrame) -> pd.DataFrame:
    """Port of rolling-window fraud features used in the source fraud notebooks."""
    df = _normalize_input_schema(transactions_df)
    if df.empty:
        return df

    df = df.sort_values(["customer_id", "TransactionDT"]).set_index("TransactionDT")

    # Transaction velocity features from agentic-ai-transaction-analysis notebooks.
    df["txn_count_1h"] = (
        df.groupby("customer_id").rolling("1h")["TransactionAmt"].count().reset_index(level=0, drop=True)
    )
    df["txn_count_24h"] = (
        df.groupby("customer_id").rolling("24h")["TransactionAmt"].count().reset_index(level=0, drop=True)
    )
    df["txn_count_7d"] = (
        df.groupby("customer_id").rolling("7D")["TransactionAmt"].count().reset_index(level=0, drop=True)
    )

    df["avg_amt_1h"] = (
        df.groupby("customer_id").rolling("1h")["TransactionAmt"].mean().reset_index(level=0, drop=True)
    )
    df["avg_amt_24h"] = (
        df.groupby("customer_id").rolling("24h")["TransactionAmt"].mean().reset_index(level=0, drop=True)
    )
    df["avg_amt_7d"] = (
        df.groupby("customer_id").rolling("7D")["TransactionAmt"].mean().reset_index(level=0, drop=True)
    )
    df["max_amt_24h"] = (
        df.groupby("customer_id").rolling("24h")["TransactionAmt"].max().reset_index(level=0, drop=True)
    )

    df["amount_dev_24h"] = df["TransactionAmt"] - df["avg_amt_24h"]
    df["std_amt_24h"] = (
        df.groupby("customer_id").rolling("24h")["TransactionAmt"].std().reset_index(level=0, drop=True)
    )
    std_nonzero = df["std_amt_24h"].replace(0, pd.NA)
    df["amount_zscore_24h"] = (df["amount_dev_24h"] / std_nonzero).fillna(0.0)

    df["hour"] = df.index.hour
    df["is_night_txn"] = df["hour"].isin([0, 1, 2, 3, 4]).astype(int)
    df["velocity_risk"] = (df["txn_count_1h"] / (df["txn_count_24h"] + 1)).fillna(0.0)

    return df.reset_index()


def _score_with_pretrained_model(feature_df: pd.DataFrame) -> pd.Series | None:
    for model_path in _candidate_model_paths():
        if model_path.exists():
            LOGGER.info("Loading pretrained fraud model from %s", model_path)
            model = joblib.load(model_path)
            if hasattr(model, "predict_proba"):
                return pd.Series(model.predict_proba(feature_df[FRAUD_FEATURES])[:, 1], index=feature_df.index)
    return None


def _score_with_isolation_forest(feature_df: pd.DataFrame) -> pd.Series:
    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(feature_df[FRAUD_FEATURES])
    iso = IsolationForest(
        n_estimators=200,
        contamination=0.03,
        random_state=42,
        n_jobs=-1,
    )
    iso.fit(x_scaled)
    scores = -iso.score_samples(x_scaled)
    min_score = float(scores.min())
    max_score = float(scores.max())
    if max_score == min_score:
        normalized = pd.Series([0.0] * len(scores), index=feature_df.index)
    else:
        normalized = pd.Series((scores - min_score) / (max_score - min_score), index=feature_df.index)
    return normalized


def detect_transaction_anomalies(transactions_df: pd.DataFrame) -> pd.DataFrame:
    """Input: transactions dataframe. Output: anomaly scores dataframe.

    Output schema is fixed to:
    - transaction_id
    - anomaly_score
    - anomaly_flag
    """
    if transactions_df.empty:
        return pd.DataFrame(columns=["transaction_id", "anomaly_score", "anomaly_flag"])

    required = {"transaction_id", "amount"}
    missing = required - set(transactions_df.columns)
    if missing:
        raise ValueError(f"Missing required transaction columns: {sorted(missing)}")

    feature_df = _engineer_fraud_features(transactions_df)
    for col in FRAUD_FEATURES:
        feature_df[col] = pd.to_numeric(feature_df.get(col, 0.0), errors="coerce").fillna(0.0)

    model_scores = _score_with_pretrained_model(feature_df)
    anomaly_score = model_scores if model_scores is not None else _score_with_isolation_forest(feature_df)
    anomaly_score = anomaly_score.clip(0.0, 1.0)
    anomaly_flag = (anomaly_score >= 0.75).astype(int)

    return pd.DataFrame(
        {
            "transaction_id": feature_df["transaction_id"],
            "anomaly_score": anomaly_score,
            "anomaly_flag": anomaly_flag,
        }
    )
