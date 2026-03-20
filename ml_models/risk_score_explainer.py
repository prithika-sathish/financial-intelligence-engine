"""
Risk Score Explainer

Computes interpretable risk scores with feature contribution breakdown.
Uses weighted formula (OPTION A) for maximum interpretability.

Every risk score is decomposable into:
- Input features (transaction volatility, anomaly frequency, etc.)
- Weights (assigned based on domain expertise)
- Contribution (feature_value × weight × 100)
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from ml_models.explainability import ExplainabilityEngine, RiskScoreExplanation

LOGGER = logging.getLogger(__name__)


class RiskScoreExplainer:
    """
    Computes transparent, explainable risk scores using weighted formula.
    """

    def __init__(self):
        self.explainability_engine = ExplainabilityEngine()
        self.weights = self.explainability_engine.RISK_FORMULA_WEIGHTS

    def compute_risk_and_explanation(
        self,
        company_id: str,
        features_dict: dict[str, float],
    ) -> tuple[float, RiskScoreExplanation]:
        """
        Compute risk score and generate full explanation.

        Args:
            company_id: Company identifier
            features_dict: Dictionary of features with names from RISK_FORMULA_WEIGHTS

        Returns:
            Tuple of (risk_score, explanation)
        """
        # Normalize features to [0, 1]
        normalized_features = self._normalize_features(features_dict)

        # Compute risk score using weighted formula
        risk_score = self._compute_weighted_risk(normalized_features)

        # Rescale to 0-100
        risk_score_normalized = risk_score * 100

        # Get explanation
        explanation = self.explainability_engine.explain_risk_score(
            company_id=company_id,
            final_risk_score=risk_score_normalized,
            features=normalized_features,
        )

        return risk_score_normalized, explanation

    def _normalize_features(self, features_dict: dict[str, float]) -> dict[str, float]:
        """
        Normalize features to [0, 1] range.

        Features that are already probabilities (0-1) pass through.
        Features like transaction volumes are clipped to [0, 1].
        Missing features default to 0.

        Args:
            features_dict: Raw features

        Returns:
            Normalized features
        """
        normalized = {}

        # Define expected ranges for normalization
        feature_ranges = {
            "transaction_volatility": (0.0, 1.0),  # std dev of amounts / mean
            "anomaly_frequency": (0.0, 1.0),  # % of anomalous txns (0-100% → 0-1)
            "credit_debt_signals": (0.0, 1.0),  # composite score
            "network_exposure": (0.0, 1.0),  # network centrality (already 0-1)
            "event_impact": (0.0, 1.0),  # recent event severity score
        }

        for feature_name in self.weights.keys():
            if feature_name in features_dict:
                value = float(features_dict[feature_name])
                # Clip to [0, 1]
                min_val, max_val = feature_ranges.get(feature_name, (0.0, 1.0))
                normalized[feature_name] = max(min_val, min(max_val, value))
            else:
                # Missing features default to 0 (no risk contribution)
                normalized[feature_name] = 0.0

        return normalized

    def _compute_weighted_risk(self, normalized_features: dict[str, float]) -> float:
        """
        Compute risk score as weighted sum of normalized features.

        Formula:
            risk_score = Σ(feature_value × weight)
            where all features ∈ [0, 1] and Σ(weights) = 1.0

        Result is in [0, 1].

        Args:
            normalized_features: Features normalized to [0, 1]

        Returns:
            Risk score in [0, 1]
        """
        risk = 0.0
        for feature_name, weight in self.weights.items():
            feature_value = normalized_features.get(feature_name, 0.0)
            contribution = feature_value * weight
            risk += contribution
            LOGGER.debug(
                f"  {feature_name}: {feature_value:.3f} × {weight:.2f} = {contribution:.3f}"
            )

        return risk

    def explain_feature_importance(
        self, explanation: RiskScoreExplanation
    ) -> pd.DataFrame:
        """
        Convert feature contributions to DataFrame for visualization.

        Args:
            explanation: RiskScoreExplanation object

        Returns:
            DataFrame with feature names, weights, and contributions
        """
        rows = []
        for feature_name, weight in explanation.feature_weights.items():
            contribution = explanation.feature_contributions.get(feature_name, 0.0)
            rows.append(
                {
                    "feature": feature_name,
                    "weight": weight,
                    "weight_pct": f"{weight*100:.1f}%",
                    "contribution": contribution,
                    "contribution_pct": f"{contribution:.1f}%",
                }
            )

        return pd.DataFrame(rows).sort_values("contribution", ascending=False)

    def build_features_from_data(
        self,
        company_id: str,
        transactions_df: pd.DataFrame,
        anomaly_scores_df: pd.DataFrame,
        events_df: pd.DataFrame,
        graph_metrics_df: pd.DataFrame,
    ) -> dict[str, float]:
        """
        Build risk features for a company from raw data.

        This is the critical step: converting raw data into features
        that feed into the risk formula.

        Args:
            company_id: Company to analyze
            transactions_df: All transactions
            anomaly_scores_df: Anomaly scores (matched on transaction_id)
            events_df: Events (matched on company_id)
            graph_metrics_df: Network metrics (indexed by company_id)

        Returns:
            Dictionary of features for this company
        """
        features = {
            "transaction_volatility": 0.0,
            "anomaly_frequency": 0.0,
            "credit_debt_signals": 0.0,
            "network_exposure": 0.0,
            "event_impact": 0.0,
        }

        # =====================================================================
        # Feature 1: TRANSACTION VOLATILITY
        # =====================================================================
        company_txns = transactions_df[
            transactions_df["company_id"] == company_id
        ].copy()
        if not company_txns.empty and "amount" in company_txns.columns:
            company_txns["amount"] = pd.to_numeric(
                company_txns["amount"], errors="coerce"
            ).fillna(0.0)
            amounts = company_txns["amount"]
            mean_amt = amounts.mean()
            if mean_amt > 0:
                volatility = amounts.std() / mean_amt
                # Clip to [0, 1]: volatility > 1.0 = max risk
                features["transaction_volatility"] = min(1.0, volatility)
                LOGGER.debug(
                    f"[{company_id}] Transaction volatility: {volatility:.3f} → {features['transaction_volatility']:.3f}"
                )

        # =====================================================================
        # Feature 2: ANOMALY FREQUENCY
        # =====================================================================
        if not company_txns.empty and not anomaly_scores_df.empty:
            merged = company_txns.merge(
                anomaly_scores_df, on="transaction_id", how="left"
            )
            if "anomaly_flag" in merged.columns:
                anomaly_flag = pd.to_numeric(
                    merged["anomaly_flag"], errors="coerce"
                ).fillna(0)
                anomaly_freq = anomaly_flag.mean()  # already in [0, 1]
                features["anomaly_frequency"] = anomaly_freq
                LOGGER.debug(
                    f"[{company_id}] Anomaly frequency: {anomaly_freq:.3f}"
                )

        # =====================================================================
        # Feature 3: CREDIT/DEBT SIGNALS
        # =====================================================================
        # Proxy: supplier concentration (high concentration = more credit risk)
        if not company_txns.empty and "supplier_id" in company_txns.columns:
            supplier_counts = company_txns["supplier_id"].value_counts(normalize=True)
            hhi = (
                (supplier_counts**2).sum()
            )  # Herfindahl-Hirschman Index
            features["credit_debt_signals"] = hhi
            LOGGER.debug(
                f"[{company_id}] Supplier concentration (HHI): {hhi:.3f}"
            )

        # =====================================================================
        # Feature 4: NETWORK EXPOSURE
        # =====================================================================
        if not graph_metrics_df.empty:
            company_metrics = graph_metrics_df[
                graph_metrics_df["company_id"] == company_id
            ]
            if not company_metrics.empty:
                if "network_exposure_score" in company_metrics.columns:
                    exposure = company_metrics["network_exposure_score"].iloc[0]
                    features["network_exposure"] = max(0.0, min(1.0, float(exposure)))
                elif "company_degree_centrality" in company_metrics.columns:
                    # Fallback to degree centrality
                    exposure = company_metrics["company_degree_centrality"].iloc[0]
                    features["network_exposure"] = max(0.0, min(1.0, float(exposure)))
                LOGGER.debug(
                    f"[{company_id}] Network exposure: {features['network_exposure']:.3f}"
                )

        # =====================================================================
        # Feature 5: EVENT IMPACT
        # =====================================================================
        if not events_df.empty:
            company_events = events_df[events_df["company_id"] == company_id]
            if not company_events.empty:
                if "event_impact_score" in company_events.columns:
                    max_impact = pd.to_numeric(
                        company_events["event_impact_score"], errors="coerce"
                    ).max()
                    if pd.notna(max_impact):
                        features["event_impact"] = max(
                            0.0, min(1.0, float(max_impact))
                        )
                # Also consider recent negative sentiment
                if "sentiment" in company_events.columns:
                    negative_count = (
                        company_events["sentiment"]
                        .astype(str)
                        .str.lower()
                        .str.contains("neg", na=False)
                        .sum()
                    )
                    event_impact_from_sentiment = min(
                        1.0, negative_count / len(company_events)
                    )
                    features["event_impact"] = max(
                        features["event_impact"], event_impact_from_sentiment
                    )
                LOGGER.debug(
                    f"[{company_id}] Event impact: {features['event_impact']:.3f}"
                )

        return features

    def explain_batch(
        self,
        predictions_df: pd.DataFrame,
        features_df: pd.DataFrame,
    ) -> list[RiskScoreExplanation]:
        """
        Generate explanations for a batch of companies.

        Args:
            predictions_df: DataFrame with company_id and risk_score
            features_df: DataFrame with company features

        Returns:
            List of RiskScoreExplanation objects
        """
        explanations = []
        for _, row in predictions_df.iterrows():
            company_id = str(row.get("company_id"))

            # Get features for this company
            company_features_df = features_df[
                features_df["company_id"] == company_id
            ]
            if company_features_df.empty:
                LOGGER.warning(f"No features found for {company_id}")
                continue

            features_dict = company_features_df.iloc[0].to_dict()
            risk_score = float(row.get("risk_score", 0.0))

            explanation = self.explainability_engine.explain_risk_score(
                company_id=company_id,
                final_risk_score=risk_score,
                features=features_dict,
            )
            explanations.append(explanation)

        return explanations
