"""Context-aware recommendation generator for supplier risk management."""

from __future__ import annotations

import logging
import pandas as pd

LOGGER = logging.getLogger("workflow.recommendations")


def generate_recommendation(row: pd.Series) -> str:
    """
    Generate a human-readable recommendation based on supplier risk profile.
    
    Args:
        row: A pandas Series from the predictions dataframe containing:
            - risk_score or propagated_risk
            - estimated_cost_impact
            - systemic_importance_score
            - recommended_action
            - company_id
    
    Returns:
        A string with actionable recommendation text.
    """
    company_id = row.get("company_id", "Unknown")
    
    # Extract metrics
    risk_score = float(row.get("propagated_risk") or row.get("risk_score", 0.0))
    cost_impact = float(row.get("estimated_cost_impact", 0.0))
    criticality = row.get("systemic_importance_score", 0.0)
    if isinstance(criticality, str):
        criticality = 0.0
    else:
        criticality = float(criticality or 0.0)
    
    action = row.get("recommended_action", "Monitor")
    
    # Build risk assessment
    risk_level = "low"
    if risk_score > 0.65:
        risk_level = "critical"
    elif risk_score > 0.5:
        risk_level = "high"
    elif risk_score > 0.3:
        risk_level = "medium"
    
    cost_level = "low"
    if cost_impact > 0.7:
        cost_level = "very high"
    elif cost_impact > 0.5:
        cost_level = "high"
    elif cost_impact > 0.3:
        cost_level = "moderate"
    
    criticality_text = "critical" if criticality > 0.6 else "important" if criticality > 0.3 else "standard"
    
    # Build explanation
    factors = []
    
    if risk_score > 0.6:
        factors.append(f"Risk score at {risk_score:.2f} indicates significant exposure")
    
    if cost_impact > 0.5:
        factors.append(f"Cost impact of {cost_impact:.2f} would significantly affect operations")
    
    if criticality > 0.5:
        factors.append("Affects multiple critical downstream dependencies")
    
    # Construct recommendation
    recommendation = (
        f"Supplier {company_id} is flagged as {risk_level} risk and {criticality_text} to the supply chain.\n\n"
    )
    
    if factors:
        recommendation += "Key concerns:\n"
        for i, factor in enumerate(factors, 1):
            recommendation += f"  {i}. {factor}\n"
        recommendation += "\n"
    
    # Action-based guidance
    if action == "Replace supplier":
        recommendation += (
            f"STATUS: Immediate action required.\n"
            f"RECOMMENDATION: Initiate supplier replacement process immediately. "
            f"Cost of failure ({cost_level}) justifies transition costs. "
            f"Begin identifying alternative suppliers and transitioning volume."
        )
    elif action == "Diversify suppliers":
        recommendation += (
            f"STATUS: Action recommended.\n"
            f"RECOMMENDATION: Diversify supply from this supplier to reduce single-source risk. "
            f"Target 30-40% volume reduction while building relationships with alternatives. "
            f"Monitor for improvement over next 2-3 quarters."
        )
    else:  # Monitor
        recommendation += (
            f"STATUS: Monitoring required.\n"
            f"RECOMMENDATION: Continue close monitoring of this supplier. "
            f"Review quarterly and escalate if risk metrics deteriorate. "
            f"Establish early warning dashboards for key indicators."
        )
    
    return recommendation


def enrich_predictions_with_recommendations(predictions_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add recommendation_text column to predictions dataframe.
    
    Args:
        predictions_df: DataFrame with supplier risk predictions
    
    Returns:
        DataFrame with added recommendation_text column
    """
    df = predictions_df.copy()
    df["recommendation_text"] = df.apply(generate_recommendation, axis=1)
    LOGGER.info("Generated recommendations for %d suppliers", len(df))
    return df
