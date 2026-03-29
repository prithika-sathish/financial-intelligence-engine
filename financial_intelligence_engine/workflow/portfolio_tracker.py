"""Portfolio state tracking for supplier status management."""

from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime

import pandas as pd

LOGGER = logging.getLogger("workflow.portfolio")


def _determine_supplier_status(risk_score: float) -> str:
    """
    Determine supplier status based on risk score.
    
    Args:
        risk_score: Propagated risk score (0-1)
    
    Returns:
        Status string: "high_risk", "watchlist", or "stable"
    """
    if risk_score > 0.7:
        return "high_risk"
    elif risk_score > 0.4:
        return "watchlist"
    else:
        return "stable"


def track_portfolio_state(
    predictions_df: pd.DataFrame,
    output_dir: Path,
) -> pd.DataFrame:
    """
    Create portfolio state tracking dataframe and save to CSV.
    
    Args:
        predictions_df: Current predictions with risk scores
        output_dir: Directory to save portfolio state
    
    Returns:
        Portfolio state dataframe with supplier status and tracking
    """
    df = predictions_df.copy()
    
    # Use propagated risk if available, else use base risk score
    risk_col = "propagated_risk" if "propagated_risk" in df.columns else "risk_score"
    df[risk_col] = pd.to_numeric(df[risk_col], errors="coerce").fillna(0.0)
    
    # Create portfolio state
    portfolio_df = pd.DataFrame({
        "supplier_id": df.get("company_id", df.get("supplier_id", "")),
        "last_risk_score": df[risk_col],
        "last_cost_impact": pd.to_numeric(df.get("estimated_cost_impact", 0.0), errors="coerce").fillna(0.0),
        "last_action": df.get("recommended_action", "Monitor"),
        "status": df[risk_col].apply(_determine_supplier_status),
        "criticality": pd.to_numeric(df.get("systemic_importance_score", 0.0), errors="coerce").fillna(0.0),
        "updated_at": datetime.utcnow().isoformat(),
    })
    
    # Filter out rows with missing supplier_id
    portfolio_df = portfolio_df[portfolio_df["supplier_id"].notna() & (portfolio_df["supplier_id"] != "")]
    
    # Save as CSV
    output_dir.mkdir(exist_ok=True, parents=True)
    portfolio_path = output_dir / "portfolio_state.csv"
    portfolio_df.to_csv(portfolio_path, index=False)
    
    LOGGER.info("Portfolio state saved to %s | total_suppliers=%d", portfolio_path, len(portfolio_df))
    
    # Log status distribution
    status_counts = portfolio_df["status"].value_counts().to_dict()
    LOGGER.info("Portfolio status distribution: %s", status_counts)
    
    return portfolio_df


def get_portfolio_summary(portfolio_df: pd.DataFrame) -> dict:
    """
    Generate summary statistics for portfolio.
    
    Args:
        portfolio_df: Portfolio state dataframe
    
    Returns:
        Dictionary with portfolio summary metrics
    """
    if portfolio_df.empty:
        return {
            "total_suppliers": 0,
            "high_risk_count": 0,
            "watchlist_count": 0,
            "stable_count": 0,
            "avg_risk_score": 0.0,
            "avg_criticality": 0.0,
        }
    
    status_counts = portfolio_df["status"].value_counts()
    
    return {
        "total_suppliers": len(portfolio_df),
        "high_risk_count": int(status_counts.get("high_risk", 0)),
        "watchlist_count": int(status_counts.get("watchlist", 0)),
        "stable_count": int(status_counts.get("stable", 0)),
        "avg_risk_score": float(portfolio_df["last_risk_score"].mean()),
        "avg_criticality": float(portfolio_df["criticality"].mean()),
        "high_criticality_suppliers": int(
            len(portfolio_df[portfolio_df["criticality"] > 0.6])
        ),
    }


def compare_portfolio_states(
    previous_state: pd.DataFrame,
    current_state: pd.DataFrame,
) -> dict:
    """
    Compare two portfolio states to detect changes.
    
    Args:
        previous_state: Previous portfolio state
        current_state: Current portfolio state
    
    Returns:
        Dictionary with change analysis
    """
    improvements = 0
    deteriorations = 0
    status_changes = 0
    
    for _, curr_row in current_state.iterrows():
        supplier_id = curr_row["supplier_id"]
        prev_rows = previous_state[previous_state["supplier_id"] == supplier_id]
        
        if prev_rows.empty:
            continue
        
        prev_row = prev_rows.iloc[0]
        prev_risk = float(prev_row["last_risk_score"])
        curr_risk = float(curr_row["last_risk_score"])
        
        if curr_risk < prev_risk - 0.05:
            improvements += 1
        elif curr_risk > prev_risk + 0.05:
            deteriorations += 1
        
        if prev_row["status"] != curr_row["status"]:
            status_changes += 1
    
    return {
        "improvements": improvements,
        "deteriorations": deteriorations,
        "status_changes": status_changes,
    }
