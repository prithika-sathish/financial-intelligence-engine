"""
Quick Reference: Explainability API Usage

This file shows how to use the explainability system from code.
"""

# ============================================================================
# PART 1: RISK SCORE EXPLANATION
# ============================================================================

# Import
from ml_models.risk_score_explainer import RiskScoreExplainer

# Create explainer
explainer = RiskScoreExplainer()

# Explain a single company's risk score
features = {
    "transaction_volatility": 0.35,      # std_dev / mean
    "anomaly_frequency": 0.08,            # % of transactions
    "credit_debt_signals": 0.42,          # supplier concentration
    "network_exposure": 0.55,             # degree centrality
    "event_impact": 0.12,                 # recent event severity
}

risk_score, explanation = explainer.compute_risk_and_explanation(
    company_id="COMP-ALPHA",
    features_dict=features,
)

print(f"Risk Score: {explanation.final_risk_score:.1f}/100 ({explanation.risk_level})")
print(f"Interpretation: {explanation.interpretation}")

# Display feature contributions
contrib_df = explainer.explain_feature_importance(explanation)
print(contrib_df[["feature", "contribution_pct"]])

# EXPECTED OUTPUT:
# Risk Score: 42.3/100 (medium)
# Interpretation: Risk score of 42.3/100 (medium). Top drivers: network_exposure (13.75%), 
#                 anomaly_frequency (2.0%), transaction_volatility (7.0%), ...
# 
#               feature  contribution_pct
#   network_exposure            13.75%
# transaction_volatility            7.00%
#   credit_debt_signals           8.4%
#   event_impact                  1.8%
# anomaly_frequency               2.0%


# ============================================================================
# PART 2: ANOMALY DETECTION EXPLANATION
# ============================================================================

from ml_models.anomaly_explainer import AnomalyDetectionExplainer
import pandas as pd
import numpy as np

# Create explainer
anomaly_explainer = AnomalyDetectionExplainer()

# Get methodology
methodology = anomaly_explainer.get_methodology_explanation()
print(f"Method: {methodology.method}")
print(f"Reasoning:\n{methodology.reasoning}")
print(f"Threshold: {methodology.threshold}")
print(f"Method Confidence: {methodology.confidence_score:.0%}")

# Detect anomalies in transaction features
# Must have numeric features: amount, txn_count_1h, txn_count_24h, etc.
transaction_features = pd.DataFrame({
    "amount": [100, 250, 150, 5000, 120, 180],  # 5000 is anomalous
    "txn_count_24h": [3, 2, 4, 15, 2, 3],
    "avg_amount_24h": [120, 200, 140, 4500, 130, 150],
})

anomaly_flags, anomaly_scores = anomaly_explainer.detect_anomalies(transaction_features)

# Annotate with explanations
transactions_with_explanation = anomaly_explainer.add_anomaly_explanations(
    transaction_features,
    anomaly_flags,
    anomaly_scores,
)

print(transactions_with_explanation[["anomaly_flag", "anomaly_score", "anomaly_explanation"]])

# Analyze distribution
dist = anomaly_explainer.analyze_anomaly_distribution(anomaly_scores, anomaly_flags)
print(f"Flagged: {dist['flagged_anomalies']} / {dist['total_transactions']}")
print(f"Interpretation: {dist['interpretation']}")

# Threshold analysis
threshold_info = anomaly_explainer.explain_at_threshold(anomaly_scores, threshold=0.65)
print(f"At threshold 0.65: {threshold_info['transactions_flagged']} transactions flagged")


# ============================================================================
# PART 3: NETWORK GRAPH EXPLANATION
# ============================================================================

from ml_models.network_explainer import NetworkGraphExplainer
import networkx as nx

# Create explainer
network_explainer = NetworkGraphExplainer()

# Get network definition
network_def = network_explainer.get_network_definition()
print(f"Edge Type: {network_def.edge_type}")
print(f"Definition: {network_def.definition}")
print(f"Risk Interpretation: {network_def.risk_interpretation}")

# Build network from transactions
transactions = pd.DataFrame({
    "company_id": ["COMP-A", "COMP-B", "COMP-C", "COMP-A"],
    "supplier_id": ["SUP-X", "SUP-X", "SUP-Y", "SUP-X"],
    "amount": [1000, 2000, 1500, 500],
})

graph = network_explainer.build_supply_chain_network(transactions)

# Compute all centrality metrics
centrality_df = network_explainer.compute_all_centrality_metrics(graph)
print(centrality_df[["company_id", "degree", "in_degree", "out_degree", "betweenness_centrality"]])

# Analyze specific node
exposure = network_explainer.compute_node_risk_exposure(graph, "COMP-A")
print(f"\n{exposure['explanation']}")
print(f"In-Degree: {exposure['in_degree_count']}")
print(f"Out-Degree: {exposure['out_degree_count']}")
print(f"Total Exposure: {exposure['total_exposure']:.3f}")

# Identify risk clusters
clusters = network_explainer.identify_risk_clusters(graph)
print(f"Clusters: {clusters}")


# ============================================================================
# PART 4: GROUNDED AI QUERY
# ============================================================================

from ml_models.explainability import ExplainabilityEngine

# Create engine
engine = ExplainabilityEngine()

# Example predictions, network, trends, events (populate with real data)
predictions_df = pd.DataFrame({
    "company_id": ["COMP-A", "COMP-B", "COMP-C"],
    "propagated_risk": [0.75, 0.45, 0.85],
})

network_df = pd.DataFrame({
    "company_id": ["COMP-A", "COMP-B", "COMP-C"],
    "systemic_importance_score": [0.65, 0.30, 0.80],
})

trends_df = pd.DataFrame({
    "company_id": ["COMP-A", "COMP-B", "COMP-C"],
    "risk_trend": ["increasing", "stable", "decreasing"],
})

events_df = pd.DataFrame({
    "company_id": ["COMP-A", "COMP-B"],
    "event_type": ["downgrade", "positive"],
})

# Query 1: Increasing risk
result = engine.ground_ai_query(
    question="Which companies show increasing financial risk?",
    predictions_df=predictions_df,
    network_df=network_df,
    trends_df=trends_df,
    events_df=events_df,
)
print(f"Answer: {result['answer']}")
print(f"Confidence: {result['confidence']}")
print(f"Method: {result['method']}")

# Query 2: Systemic importance
result = engine.ground_ai_query(
    question="Which company is most systemically important and why?",
    predictions_df=predictions_df,
    network_df=network_df,
    trends_df=trends_df,
    events_df=events_df,
)
print(f"\nAnswer: {result['answer']}")
print(f"Reasoning: {result['reasoning']}")

# Query 3: Unrecognized pattern
result = engine.ground_ai_query(
    question="What color is the sunset?",
    predictions_df=predictions_df,
    network_df=network_df,
    trends_df=trends_df,
    events_df=events_df,
)
print(f"\nAnswer: {result['answer']}")
print(f"Confidence: {result['confidence']} (no match, system declines to hallucinate)")


# ============================================================================
# PART 5: SYSTEM TRANSPARENCY
# ============================================================================

engine = ExplainabilityEngine()
transparency = engine.get_system_transparency()

print(f"Data Source: {transparency.data_source}")
print(f"Currency: {transparency.data_currency}")
print(f"\nAssumptions:")
for i, assumption in enumerate(transparency.model_assumptions, 1):
    print(f"  {i}. {assumption}")

print(f"\nLimitations:")
for i, limitation in enumerate(transparency.limitations, 1):
    print(f"  {i}. {limitation}")

print(f"\nNot Capable Of:")
for i, incap in enumerate(transparency.not_capable_of, 1):
    print(f"  {i}. {incap}")

print(f"\nUpdate Frequency: {transparency.update_frequency}")


# ============================================================================
# COMPLETE WORKFLOW EXAMPLE
# ============================================================================

def explain_company_risk(
    company_id: str,
    transactions_df: pd.DataFrame,
    anomaly_scores_df: pd.DataFrame,
    events_df: pd.DataFrame,
    network_df: pd.DataFrame,
) -> dict:
    """
    Complete workflow: explain a company's risk from raw data.
    """
    # Build features
    risk_scorer = RiskScoreExplainer()
    features = risk_scorer.build_features_from_data(
        company_id=company_id,
        transactions_df=transactions_df,
        anomaly_scores_df=anomaly_scores_df,
        events_df=events_df,
        graph_metrics_df=network_df,
    )
    
    # Compute risk score
    risk_score, risk_explanation = risk_scorer.compute_risk_and_explanation(
        company_id=company_id,
        features_dict=features,
    )
    
    # Get network exposure
    network_explainer = NetworkGraphExplainer()
    graph = network_explainer.build_supply_chain_network(transactions_df)
    exposure = network_explainer.compute_node_risk_exposure(graph, company_id)
    
    # Build explanation
    return {
        "company_id": company_id,
        "risk_score": risk_score,
        "risk_level": risk_explanation.risk_level,
        "interpretation": risk_explanation.interpretation,
        "feature_contributions": risk_explanation.feature_contributions,
        "network_exposure_explanation": exposure["explanation"],
        "network_exposure": exposure["total_exposure"],
    }

# Usage:
# result = explain_company_risk(
#     company_id="COMP-ALPHA",
#     transactions_df=transactions_df,
#     anomaly_scores_df=anomaly_scores_df,
#     events_df=events_df,
#     network_df=network_df,
# )
# print(f"{result['company_id']}: {result['risk_score']:.1f}/100 ({result['risk_level']})")
# print(result['interpretation'])
