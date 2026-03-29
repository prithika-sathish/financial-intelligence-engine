"""
Anomaly Detection Explainer

Provides transparency into anomaly detection methodology.

Uses Isolation Forest (preferred) for:
- Non-parametric detection (no normality assumption)
- Handles multi-dimensional feature space
- Efficient scaling
- Proven effective in fraud detection

Explains:
- Why Isolation Forest was chosen
- How the threshold is set
- Confidence score for each detection
- Visualization of normal vs anomalous patterns
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from ml_models.explainability import AnomalyExplanation, ExplainabilityEngine

LOGGER = logging.getLogger(__name__)


class AnomalyDetectionExplainer:
    """
    Provides transparency into anomaly detection using Isolation Forest.
    """

    def __init__(self, contamination: float = 0.04, random_state: int = 42):
        """
        Initialize anomaly detection explainer.

        Args:
            contamination: Expected fraction of outliers (default 4% of transactions)
            random_state: Seed for reproducibility
        """
        self.contamination = contamination
        self.random_state = random_state
        self.explainability_engine = ExplainabilityEngine()
        self.isolation_forest = IsolationForest(
            contamination=contamination,
            n_estimators=100,
            max_samples="auto",
            random_state=random_state,
            n_jobs=-1,
        )

    def get_methodology_explanation(self) -> AnomalyExplanation:
        """
        Get full explanation of anomaly detection methodology.

        Returns:
            AnomalyExplanation object
        """
        return self.explainability_engine.explain_anomaly_detection()

    def detect_anomalies(
        self, features_df: pd.DataFrame
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Detect anomalies using Isolation Forest.

        Args:
            features_df: DataFrame with transaction features
                Must have columns like: amount, txn_count_1h, txn_count_24h, etc.

        Returns:
            Tuple of (anomaly_flags, anomaly_scores)
            - anomaly_flags: -1 for anomaly, 1 for normal
            - anomaly_scores: Raw scores from Isolation Forest (higher = more anomalous)
        """
        # Select numeric features only
        numeric_cols = features_df.select_dtypes(include=[np.number]).columns
        X = features_df[numeric_cols].fillna(0.0).values

        # Fit and predict
        self.isolation_forest.fit(X)
        anomaly_flags = self.isolation_forest.predict(X)

        # Get anomaly scores (negative = more anomalous)
        # Normalize to [0, 1] for interpretation
        raw_scores = self.isolation_forest.score_samples(X)
        anomaly_scores = 1.0 / (1.0 + np.exp(-raw_scores))  # Sigmoid normalization

        return anomaly_flags, anomaly_scores

    def add_anomaly_explanations(
        self,
        transactions_df: pd.DataFrame,
        anomaly_flags: np.ndarray,
        anomaly_scores: np.ndarray,
    ) -> pd.DataFrame:
        """
        Augment transaction data with anomaly explanations and confidence scores.

        Args:
            transactions_df: Original transaction data
            anomaly_flags: Output from detect_anomalies()
            anomaly_scores: Output from detect_anomalies()

        Returns:
            DataFrame with anomaly_flag, anomaly_score, anomaly_confidence, anomaly_explanation
        """
        df = transactions_df.copy()
        df["anomaly_flag"] = anomaly_flags
        df["anomaly_score"] = anomaly_scores

        # Compute confidence for each detection
        df["anomaly_confidence"] = df.apply(
            lambda row: self.explainability_engine.compute_anomaly_confidence(
                row["anomaly_score"], row["anomaly_flag"]
            ),
            axis=1,
        )

        # Add textual explanation
        df["anomaly_explanation"] = df.apply(
            lambda row: self._get_anomaly_explanation(row), axis=1
        )

        return df

    def _get_anomaly_explanation(self, row: pd.Series) -> str:
        """
        Generate plain-English explanation for a specific transaction.

        Args:
            row: A transaction row with anomaly_flag, anomaly_score, etc.

        Returns:
            Plain text explanation
        """
        if row["anomaly_flag"] == -1:
            # Anomalous transaction
            confidence = row.get("anomaly_confidence", 0.5)
            amount = row.get("amount", "unknown")
            return (
                f"FLAGGED AS ANOMALOUS (confidence: {confidence:.1%}). "
                f"Transaction amount ${amount} deviates from normal pattern for this entity."
            )
        else:
            # Normal transaction
            confidence = row.get("anomaly_confidence", 0.5)
            return f"Normal transaction (confidence: {confidence:.1%})."

    def analyze_anomaly_distribution(
        self, anomaly_scores: np.ndarray, anomaly_flags: np.ndarray
    ) -> dict[str, Any]:
        """
        Analyze and explain the distribution of anomaly scores.

        Args:
            anomaly_scores: Anomaly scores from detect_anomalies()
            anomaly_flags: Anomaly flags from detect_anomalies()

        Returns:
            Dictionary with distribution statistics and interpretation
        """
        normal_scores = anomaly_scores[anomaly_flags == 1]
        anomalous_scores = anomaly_scores[anomaly_flags == -1]

        return {
            "method": "Isolation Forest",
            "total_transactions": len(anomaly_flags),
            "flagged_anomalies": int((anomaly_flags == -1).sum()),
            "anomaly_percentage": float((anomaly_flags == -1).sum() / len(anomaly_flags)),
            "threshold": self.explainability_engine.anomaly_config["threshold"],
            "normal_score_mean": float(normal_scores.mean()),
            "normal_score_std": float(normal_scores.std()),
            "anomalous_score_mean": float(anomalous_scores.mean()),
            "anomalous_score_std": float(anomalous_scores.std()),
            "score_separation": float(
                anomalous_scores.mean() - normal_scores.mean()
            ),  # Higher = better separation
            "interpretation": (
                f"Out of {len(anomaly_flags)} transactions, {(anomaly_flags == -1).sum()} ({(anomaly_flags == -1).sum() / len(anomaly_flags):.1%}) "
                f"were flagged as anomalous. Normal transactions have average score {normal_scores.mean():.3f}, "
                f"while anomalous transactions have average score {anomalous_scores.mean():.3f}. "
                f"This separation of {anomalous_scores.mean() - normal_scores.mean():.3f} indicates "
                f"{'strong' if anomalous_scores.mean() - normal_scores.mean() > 0.3 else 'moderate' if anomalous_scores.mean() - normal_scores.mean() > 0.1 else 'weak'} "
                f"anomaly detection performance."
            ),
        }

    def explain_at_threshold(
        self, anomaly_scores: np.ndarray, threshold: float = 0.65
    ) -> dict[str, Any]:
        """
        Explain what happens at a specific anomaly score threshold.

        Args:
            anomaly_scores: Anomaly scores
            threshold: Threshold value (0-1)

        Returns:
            Dictionary with threshold interpretation
        """
        flagged = (anomaly_scores >= threshold).sum()
        percentage = 100.0 * flagged / len(anomaly_scores)

        return {
            "threshold": threshold,
            "transactions_flagged": int(flagged),
            "percentage_flagged": float(percentage),
            "explanation": (
                f"Setting threshold to {threshold:.2f} flags {percentage:.1f}% of transactions as anomalous. "
                f"Higher threshold = fewer false positives but more missed anomalies. "
                f"Lower threshold = catches more anomalies but more false alarms."
            ),
        }

    def feature_importance_for_anomaly_detection(
        self, features_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Estimate which features are most important for anomaly detection.

        Isolation Forest does not provide feature importances natively,
        but we can approximate based on feature variance in anomalous vs normal.

        Args:
            features_df: Feature DataFrame

        Returns:
            DataFrame with feature importance scores
        """
        numeric_cols = features_df.select_dtypes(include=[np.number]).columns
        X = features_df[numeric_cols].fillna(0.0).values

        # Detect anomalies
        anomaly_flags = self.isolation_forest.predict(X)

        # Compute variance ratio: var(anomalous) / var(normal)
        importance_scores = []
        for i, col in enumerate(numeric_cols):
            normal_vals = X[anomaly_flags == 1, i]
            anomalous_vals = X[anomaly_flags == -1, i]

            normal_var = normal_vals.var()
            anomalous_var = anomalous_vals.var()

            if normal_var > 1e-9:
                importance = anomalous_var / normal_var
            else:
                importance = 1.0

            importance_scores.append(
                {
                    "feature": col,
                    "variance_anomalous": float(anomalous_var),
                    "variance_normal": float(normal_var),
                    "importance_score": float(importance),
                }
            )

        return pd.DataFrame(importance_scores).sort_values(
            "importance_score", ascending=False
        )


# ============================================================================
# Utility for visualization
# ============================================================================


def create_anomaly_comparison_data(
    df: pd.DataFrame,
    normal_label: str = "Normal",
    anomaly_label: str = "Anomalous",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split data into normal and anomalous for comparison visualizations.

    Args:
        df: DataFrame with 'anomaly_flag' column
        normal_label: Label for normal transactions
        anomaly_label: Label for anomalous transactions

    Returns:
        Tuple of (normal_df, anomalous_df) with type labels for visualization
    """
    normal = df[df["anomaly_flag"] == 1].copy()
    anomalous = df[df["anomaly_flag"] == -1].copy()

    normal["type"] = normal_label
    anomalous["type"] = anomaly_label

    return normal, anomalous
