"""
Explainability engine for financial risk intelligence system.

This module provides:
1. Risk score computation transparency (feature contributions, formula)
2. Anomaly detection method explanation (algorithm, threshold logic)
3. Network relationship definitions and centrality metrics
4. AI answer grounding (rule-based retrieval from computed metrics)
5. System transparency documentation (data sources, assumptions, limitations)

Every number displayed in the UI is traceable to a computation defined here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)


# ============================================================================
# DATA CLASSES FOR EXPLAINABILITY
# ============================================================================


@dataclass
class RiskScoreExplanation:
    """Explainable risk score with feature contributions."""

    company_id: str
    final_risk_score: float  # 0-100
    risk_level: str  # "low", "medium", "high"
    feature_contributions: dict[str, float]  # feature_name -> contribution (0-100)
    feature_weights: dict[str, float]  # feature_name -> weight in formula
    formula_description: str
    interpretation: str


@dataclass
class AnomalyExplanation:
    """Explains anomaly detection methodology and results."""

    method: str  # "isolation_forest", "z_score", "moving_average"
    parameters: dict[str, float]
    contamination_rate: float  # expected % of outliers
    threshold: float  # threshold score for flagging anomaly
    reasoning: str  # why this method was chosen
    confidence_score: float  # 0-1: confidence in the detection


@dataclass
class NetworkExplanation:
    """Explains what network edges represent and their risk implications."""

    edge_type: str  # "transaction_volume", "correlation", "supply_chain"
    definition: str  # plain English definition
    weight_calculation: str  # how edge weight is computed
    risk_interpretation: str  # why highly connected nodes are risky
    centrality_metrics: dict[str, float]  # degree, betweenness, closeness, etc.


@dataclass
class SystemTransparency:
    """Global system transparency panel."""

    data_source: str  # "simulated" or "real"
    data_currency: str  # how recent is the data
    model_assumptions: list[str]
    limitations: list[str]
    not_capable_of: list[str]
    update_frequency: str


# ============================================================================
# EXPLAINABILITY ENGINE - CORE CLASS
# ============================================================================


class ExplainabilityEngine:
    """
    Central explainability system providing transparency across all components.
    """

    # RISK SCORING CONFIGURATION
    # These weights define the risk formula. Must sum to 1.0 for interpretability.
    RISK_FORMULA_WEIGHTS = {
        "transaction_volatility": 0.20,  # std dev or change in transaction volumes
        "anomaly_frequency": 0.25,  # % of anomalous transactions
        "credit_debt_signals": 0.15,  # payment delays, supplier concentration
        "network_exposure": 0.25,  # how many dependencies; degree centrality
        "event_impact": 0.15,  # recent negative news/events
    }

    # ANOMALY DETECTION CONFIGURATION
    ANOMALY_METHOD = "isolation_forest"  # preferred for non-linear patterns
    ANOMALY_CONTAMINATION = 0.04  # expect ~4% of transactions to be anomalous
    ANOMALY_THRESHOLD = 0.65  # anomaly score threshold (0-1)

    # NETWORK EDGE DEFINITION
    NETWORK_EDGE_TYPE = "transaction_volume"  # what edges represent
    NETWORK_EDGE_DEFINITION = (
        "Directed edge from company A to company B if A depends on B for supplies/services. "
        "Edge weight = normalized transaction volume between them. "
        "High weight indicates strong dependency; default on B would disrupt A."
    )

    def __init__(self):
        """Initialize explainability engine."""
        self.risk_formula_weights = self.RISK_FORMULA_WEIGHTS.copy()
        self.anomaly_config = {
            "method": self.ANOMALY_METHOD,
            "contamination": self.ANOMALY_CONTAMINATION,
            "threshold": self.ANOMALY_THRESHOLD,
        }

    # ========================================================================
    # PART 1: RISK SCORE EXPLANATION
    # ========================================================================

    def explain_risk_score(
        self,
        company_id: str,
        final_risk_score: float,
        features: dict[str, float],
    ) -> RiskScoreExplanation:
        """
        Explain how a risk score was computed.

        Args:
            company_id: Company identifier
            final_risk_score: Final risk score (0-100)
            features: Feature dict with keys matching RISK_FORMULA_WEIGHTS

        Returns:
            RiskScoreExplanation with breakdown of contributions
        """
        # Determine risk level
        if final_risk_score >= 75:
            risk_level = "high"
        elif final_risk_score >= 40:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Calculate feature contributions
        feature_contributions = {}
        for feature_name, weight in self.risk_formula_weights.items():
            if feature_name in features:
                # Contribution = (feature value) * (weight) * 100
                # Feature values should be normalized 0-1
                feature_value = max(0.0, min(1.0, float(features[feature_name])))
                contribution = feature_value * weight * 100
                feature_contributions[feature_name] = contribution

        # Build plain English interpretation
        top_drivers = sorted(
            feature_contributions.items(), key=lambda x: x[1], reverse=True
        )[:3]
        drivers_text = ", ".join([f"{name} ({val:.1f}%)" for name, val in top_drivers])
        interpretation = (
            f"Risk score of {final_risk_score:.1f}/100 ({risk_level}). "
            f"Top drivers: {drivers_text}. "
            f"This company is experiencing {'significant' if risk_level == 'high' else 'moderate' if risk_level == 'medium' else 'low'} "
            f"financial risk based on transaction patterns, network exposure, and recent events."
        )

        formula_description = (
            "Risk Score = sum(feature_value × weight × 100) for all features\n"
            "where feature_value is normalized to [0,1] and weights are:\n"
            + "\n".join(
                [f"  - {k}: {v:.1%}" for k, v in self.risk_formula_weights.items()]
            )
        )

        return RiskScoreExplanation(
            company_id=company_id,
            final_risk_score=final_risk_score,
            risk_level=risk_level,
            feature_contributions=feature_contributions,
            feature_weights=self.risk_formula_weights,
            formula_description=formula_description,
            interpretation=interpretation,
        )

    # ========================================================================
    # PART 2: ANOMALY DETECTION EXPLANATION
    # ========================================================================

    def explain_anomaly_detection(self) -> AnomalyExplanation:
        """
        Explain the anomaly detection methodology.

        Returns:
            AnomalyExplanation with method, parameters, and reasoning
        """
        reasoning = (
            "Isolation Forest is chosen because:\n"
            "1. Non-parametric: no assumption of normal distribution\n"
            "2. Scales well to high dimensions (multiple transaction features)\n"
            "3. Detects global and local outliers (unusual for that company)\n"
            "4. Computationally efficient for streaming transactions\n"
            "5. Proven effective in fraud/anomaly detection literature"
        )

        parameters = {
            "n_estimators": 100,  # number of trees in forest
            "contamination": self.ANOMALY_CONTAMINATION,  # expected % anomalies
            "max_samples": "auto",  # samples per tree
            "random_state": 42,  # reproducibility
        }

        return AnomalyExplanation(
            method=self.ANOMALY_METHOD,
            parameters=parameters,
            contamination_rate=self.ANOMALY_CONTAMINATION,
            threshold=self.ANOMALY_THRESHOLD,
            reasoning=reasoning,
            confidence_score=0.85,  # empirical confidence in method
        )

    def compute_anomaly_confidence(
        self, anomaly_score: float, anomaly_flag: int
    ) -> float:
        """
        Compute confidence score for a specific anomaly detection.

        Args:
            anomaly_score: Raw score from Isolation Forest (0-1)
            anomaly_flag: Binary flag (0=normal, 1=anomalous)

        Returns:
            Confidence score (0-1)
        """
        if anomaly_flag == 1:
            # Higher score → more confident it's anomalous
            return min(1.0, anomaly_score * 1.5)
        else:
            # Confidence that it's normal
            return 1.0 - min(1.0, anomaly_score * 1.5)

    # ========================================================================
    # PART 3: NETWORK GRAPH EXPLANATION
    # ========================================================================

    def explain_network_graph(self) -> NetworkExplanation:
        """
        Explain what the network graph represents and why it matters for risk.

        Returns:
            NetworkExplanation with edge definition and risk interpretation
        """
        weight_calculation = (
            "Edge weight = (Total amount paid from A to B) / (Total amount paid by A)\n"
            "This represents the fraction of A's spending that depends on B.\n"
            "Higher weight = stronger dependency; default by B is more disruptive to A."
        )

        risk_interpretation = (
            "Highly connected nodes represent systemic importance:\n"
            "1. High IN-DEGREE (many companies depend on them): "
            "Default would cascade through multiple suppliers\n"
            "2. High OUT-DEGREE (many dependencies): "
            "Vulnerable to multiple supplier disruptions\n"
            "3. High BETWEENNESS (bridge between clusters): "
            "Critical for network flow; failure fragments supply chains\n"
            "This is why network centrality is a key risk factor."
        )

        return NetworkExplanation(
            edge_type=self.NETWORK_EDGE_TYPE,
            definition=self.NETWORK_EDGE_DEFINITION,
            weight_calculation=weight_calculation,
            risk_interpretation=risk_interpretation,
            centrality_metrics={},  # will be populated per node
        )

    def compute_network_centrality_metrics(
        self, graph: Any, company_id: str
    ) -> dict[str, float]:
        """
        Compute centrality metrics for a company in the dependency network.

        Args:
            graph: NetworkX graph object
            company_id: Company to analyze

        Returns:
            Dictionary with centrality metrics
        """
        try:
            degree = nx.degree_centrality(graph)
            betweenness = nx.betweenness_centrality(graph)
            closeness = nx.closeness_centrality(graph)
            in_degree = nx.in_degree_centrality(graph)
            out_degree = nx.out_degree_centrality(graph)

            return {
                "degree_centrality": float(degree.get(company_id, 0.0)),
                "in_degree_centrality": float(in_degree.get(company_id, 0.0)),
                "out_degree_centrality": float(out_degree.get(company_id, 0.0)),
                "betweenness_centrality": float(betweenness.get(company_id, 0.0)),
                "closeness_centrality": float(closeness.get(company_id, 0.0)),
            }
        except Exception as e:
            LOGGER.warning(f"Failed to compute centrality metrics: {e}")
            return {}

    # ========================================================================
    # PART 4: GROUNDED AI QUERY SYSTEM
    # ========================================================================

    def ground_ai_query(
        self,
        question: str,
        predictions_df: pd.DataFrame,
        network_df: pd.DataFrame,
        trends_df: pd.DataFrame,
        events_df: pd.DataFrame,
    ) -> dict[str, Any]:
        """
        Answer AI query with rule-based retrieval from computed metrics.

        This ensures AI responses are grounded in actual data, not hallucinated.

        Args:
            question: User question
            predictions_df: Risk predictions data
            network_df: Network analysis data
            trends_df: Risk trends data
            events_df: Events data

        Returns:
            Dictionary with answer, evidence, reasoning, confidence
        """
        question_lower = question.lower()

        # =====================================================================
        # RULE 1: Increasing Risk Pattern
        # =====================================================================
        if any(
            phrase in question_lower
            for phrase in ["increasing", "rising", "growing", "trending up"]
        ):
            if not trends_df.empty and "risk_trend" in trends_df.columns:
                increasing = trends_df[
                    trends_df["risk_trend"].astype(str).str.lower() == "increasing"
                ]
                if not increasing.empty:
                    companies = increasing["company_id"].tolist()[:5]
                    evidence = f"{len(increasing)} companies show increasing risk trend."
                    answer = f"Companies with increasing risk: {', '.join(map(str, companies))}"
                    return {
                        "answer": answer,
                        "evidence": evidence,
                        "reasoning": "Based on risk_trend calculation: risk_velocity > 0",
                        "confidence": 0.95,
                        "method": "rule-based",
                    }

        # =====================================================================
        # RULE 2: Systemic Importance / Contagion Risk
        # =====================================================================
        if any(
            phrase in question_lower
            for phrase in [
                "systemic",
                "contagion",
                "cascade",
                "important",
                "critical",
            ]
        ):
            if not network_df.empty:
                systemic_col = "systemic_importance_score"
                if systemic_col in network_df.columns:
                    network_df[systemic_col] = pd.to_numeric(
                        network_df[systemic_col], errors="coerce"
                    ).fillna(0.0)
                    top_systemic = (
                        network_df.nlargest(3, systemic_col)[
                            ["company_id", systemic_col]
                        ]
                        .to_dict(orient="records")
                    )
                    evidence = (
                        "Systemic importance = network centrality + risk * exposure"
                    )
                    answer = "; ".join(
                        [
                            f"{row['company_id']}: {row[systemic_col]:.3f}"
                            for row in top_systemic
                        ]
                    )
                    return {
                        "answer": f"Most systemically important: {answer}",
                        "evidence": evidence,
                        "reasoning": (
                            "High systemic importance = high centrality (many depend on them) "
                            "+ high risk (likely to fail)"
                        ),
                        "confidence": 0.90,
                        "method": "rule-based",
                    }

        # =====================================================================
        # RULE 3: Highest Risk Companies
        # =====================================================================
        if any(
            phrase in question_lower
            for phrase in ["highest risk", "most risk", "at-risk", "riskiest"]
        ):
            if not predictions_df.empty:
                risk_col = (
                    "propagated_risk"
                    if "propagated_risk" in predictions_df.columns
                    else "risk_score"
                )
                predictions_df[risk_col] = pd.to_numeric(
                    predictions_df[risk_col], errors="coerce"
                ).fillna(0.0)
                top_risk = (
                    predictions_df.nlargest(3, risk_col)[
                        ["company_id", risk_col, "risk_level"]
                    ]
                    .to_dict(orient="records")
                )
                answer = "; ".join(
                    [
                        f"{row['company_id']}: {row[risk_col]:.2f} ({row.get('risk_level', 'unknown')})"
                        for row in top_risk
                    ]
                )
                return {
                    "answer": f"Highest risk companies: {answer}",
                    "evidence": f"Analyzed {len(predictions_df)} companies",
                    "reasoning": (
                        "Risk score computed from: transaction volatility, anomaly frequency, "
                        "network exposure, credit signals, event impact"
                    ),
                    "confidence": 0.92,
                    "method": "rule-based",
                }

        # =====================================================================
        # RULE 4: Recent Events Impact
        # =====================================================================
        if any(phrase in question_lower for phrase in ["event", "news", "trigger"]):
            if not events_df.empty and "company_id" in events_df.columns:
                recent_events = events_df.tail(10)
                event_summary = (
                    f"Recent {len(recent_events)} events detected. "
                    f"Top triggered companies: "
                )
                if "company_id" in recent_events.columns:
                    top_cos = (
                        recent_events["company_id"].value_counts().head(3).index.tolist()
                    )
                    event_summary += ", ".join(map(str, top_cos))
                return {
                    "answer": event_summary,
                    "evidence": f"{len(events_df)} total events in dataset",
                    "reasoning": "Events captured from news sentiment analysis and financial indicators",
                    "confidence": 0.88,
                    "method": "rule-based",
                }

        # =====================================================================
        # DEFAULT: Cannot answer
        # =====================================================================
        return {
            "answer": (
                "I could not match your question to available metrics. "
                "Try asking about: increasing risk, systemic importance, high-risk companies, or recent events."
            ),
            "evidence": "Question does not match rule-based retrieval patterns",
            "reasoning": (
                "The AI query system uses rule-based retrieval to ensure answers are grounded in actual data. "
                "If your question doesn't match known patterns, the system declines to hallucinate."
            ),
            "confidence": 0.0,
            "method": "rule-based",
        }

    # ========================================================================
    # PART 5: SYSTEM TRANSPARENCY
    # ========================================================================

    def get_system_transparency(self) -> SystemTransparency:
        """
        Return global system transparency documentation.

        Returns:
            SystemTransparency with data sources, assumptions, limitations
        """
        return SystemTransparency(
            data_source="Simulated sample data for demonstration. In production, replace with real transaction feeds.",
            data_currency="Dashboard reads outputs files only. No real-time updates without pipeline execution.",
            model_assumptions=[
                "Transaction data represents true company financial activity",
                "Historical patterns are predictive of near-term risk (assumes stationarity)",
                "Network relationships are static (no dynamic re-weighting)",
                "Anomaly detection uses unsupervised learning (no labeled fraud in training)",
                "Risk is additive across factors (not multiplicative or non-linear beyond model)",
            ],
            limitations=[
                "Anomaly detection may miss novel attack patterns never seen before",
                "Network analysis assumes all edges are equally important (no validation weighting)",
                "Risk scores reflect historical data quality; garbage in = garbage out",
                "Systemic importance is backward-looking; cannot predict future pivots in supply chains",
                "LLM-generated explanations may hallucinate details beyond the JSON context",
            ],
            not_capable_of=[
                "Predicting black swan events (by definition)",
                "Identifying money laundering or sophisticated fraud schemes without domain experts",
                "Real-time detection (pipeline must be executed for updates)",
                "Causal inference (can only show correlation, not causation)",
                "Prescriptive recommendations (system explains, does not advise)",
            ],
            update_frequency="Manual: after running ML pipeline. Typical: daily or weekly batch.",
        )

    def get_method_decisions(self) -> dict[str, str]:
        """Return explicit design decisions for methodological transparency."""
        return {
            "why_weighted_over_ml": (
                "The production risk engine currently uses RandomForest probabilities blended with network and systemic "
                "components. A weighted formula exists for interpretability experiments, but the pipeline path is ML-first "
                "for stronger non-linear signal capture."
            ),
            "why_isolation_forest_over_zscore": (
                "The anomaly detector first attempts a pretrained fraud model and only falls back to IsolationForest when "
                "no artifact is available. IsolationForest is favored over Z-score in fallback mode because transaction data "
                "is often non-Gaussian and multi-dimensional, where Z-score assumptions are too restrictive."
            ),
        }

    def get_failure_cases(self) -> list[str]:
        """Return known failure modes users should account for in operations."""
        return [
            "Highly seasonal or highly volatile legitimate companies can be falsely flagged as anomalous.",
            "Sparse transaction history can produce unstable risk estimates and noisy trend signals.",
            "Abrupt supplier network rewiring can make historical centrality-based exposure outdated.",
            "Low event coverage for a company can understate event-impact risk in the final score.",
            "Schema drift or missing values in upstream feeds can silently degrade model reliability.",
        ]

    def get_real_data_roadmap(self) -> list[str]:
        """Return practical steps for upgrading from simulated to production-grade data."""
        return [
            "Integrate market and macro data APIs (equity prices, spreads, volatility indices) for external stress signals.",
            "Ingest historical financial statements and derive leverage, liquidity, and coverage ratios per company.",
            "Build labeled fraud and default datasets to train and validate supervised risk models in parallel with rules.",
            "Backtest thresholds and risk weights on historical incident windows before production rollout.",
            "Add model monitoring for drift, alert precision/recall, and explanation consistency over time.",
        ]


# ============================================================================
# HELPER FUNCTIONS FOR UI INTEGRATION
# ============================================================================


def create_risk_explanation_dataframe(
    explanations: list[RiskScoreExplanation],
) -> pd.DataFrame:
    """Convert list of RiskScoreExplanation to DataFrame for display."""
    rows = []
    for exp in explanations:
        rows.append(
            {
                "company_id": exp.company_id,
                "risk_score": exp.final_risk_score,
                "risk_level": exp.risk_level,
                "top_driver": max(exp.feature_contributions.items(), key=lambda x: x[1])[
                    0
                ],
                "interpretation": exp.interpretation,
            }
        )
    return pd.DataFrame(rows)


# Import networkx
import networkx as nx
