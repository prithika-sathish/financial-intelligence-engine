from __future__ import annotations

import pandas as pd


def recommend_actions(
    predictions_df: pd.DataFrame,
    risk_col: str = "propagated_risk",
    cost_col: str = "estimated_cost_impact",
) -> pd.DataFrame:
    """Add recommended_action using deterministic business rules."""
    out = predictions_df.copy()
    if out.empty:
        out["recommended_action"] = []
        return out

    risk = pd.to_numeric(out.get(risk_col, out.get("risk_score", 0.0)), errors="coerce").fillna(0.0)
    cost = pd.to_numeric(out.get(cost_col, 0.0), errors="coerce").fillna(0.0)

    out["recommended_action"] = "Monitor"
    out.loc[risk > 0.5, "recommended_action"] = "Diversify suppliers"
    out.loc[(risk > 0.7) & (cost > 0.6), "recommended_action"] = "Replace supplier"
    return out
