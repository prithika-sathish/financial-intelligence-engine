from __future__ import annotations

import pandas as pd


def _normalize(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").fillna(0.0).astype(float)
    return (numeric - numeric.min()) / (numeric.max() - numeric.min() + 1e-8)


def _compute_dependency_weight(
    company_ids: pd.Series,
    dependency_edges_df: pd.DataFrame,
    transactions_df: pd.DataFrame,
) -> pd.Series:
    node_ids = company_ids.astype(str)

    if not dependency_edges_df.empty and {"from_company_id", "to_company_id", "weight"}.issubset(dependency_edges_df.columns):
        edges = dependency_edges_df.copy()
        edges["from_company_id"] = edges["from_company_id"].astype(str)
        edges["to_company_id"] = edges["to_company_id"].astype(str)
        edges["weight"] = pd.to_numeric(edges["weight"], errors="coerce").fillna(0.0).clip(lower=0.0)

        outgoing = edges.groupby("from_company_id", dropna=False)["weight"].mean().rename("outgoing_weight")
        incoming = edges.groupby("to_company_id", dropna=False)["weight"].mean().rename("incoming_weight")

        out = node_ids.map(outgoing).fillna(0.0)
        inn = node_ids.map(incoming).fillna(0.0)
        weight = 0.6 * out + 0.4 * inn
        return _normalize(weight).clip(0.0, 1.0)

    tx = transactions_df.copy()
    if "company_id" not in tx.columns:
        return pd.Series([0.0] * len(node_ids), index=company_ids.index)

    interaction_count = tx.groupby("company_id", dropna=False).size().rename("interaction_count")
    return _normalize(node_ids.map(interaction_count).fillna(0.0)).clip(0.0, 1.0)


def _compute_base_cost(company_ids: pd.Series, transactions_df: pd.DataFrame) -> pd.Series:
    tx = transactions_df.copy()
    if tx.empty or "company_id" not in tx.columns:
        return pd.Series([0.0] * len(company_ids), index=company_ids.index)

    tx["amount"] = pd.to_numeric(tx.get("amount", 0.0), errors="coerce").fillna(0.0)
    spend = tx.groupby("company_id", dropna=False)["amount"].sum().rename("base_cost")
    return company_ids.astype(str).map(spend).fillna(0.0)


def add_cost_impact_and_criticality(
    predictions_df: pd.DataFrame,
    transactions_df: pd.DataFrame,
    dependency_edges_df: pd.DataFrame,
    risk_col: str = "propagated_risk",
) -> pd.DataFrame:
    """Append cost components and explainability to predictions.

    Decomposes cost into:
    - replacement_cost: cost to replace supplier (0.1-0.3x base_cost)
    - delay_cost: cost of supply chain delays (0.05-0.2x base_cost, risk-weighted)
    - dependency_cost: cost from downstream exposure (base_cost * dependency_weight * risk, capped)
    
    Total cost = replacement + delay + dependency, then normalized to [0, 1].
    Includes cost_explanation field describing the breakdown.
    
    criticality_score = number_of_dependents * avg_dependency_strength
    Both cost and criticality outputs are normalized to [0, 1].
    """
    if predictions_df.empty:
        out = predictions_df.copy()
        out["replacement_cost"] = []
        out["delay_cost"] = []
        out["dependency_cost"] = []
        out["total_cost"] = []
        out["estimated_cost_impact"] = []
        out["cost_explanation"] = []
        out["criticality_score"] = []
        return out

    out = predictions_df.copy()
    out["company_id"] = out["company_id"].astype(str)

    effective_risk = pd.to_numeric(out.get(risk_col, out.get("risk_score", 0.0)), errors="coerce").fillna(0.0)
    base_cost = _compute_base_cost(out["company_id"], transactions_df)
    dependency_weight = _compute_dependency_weight(out["company_id"], dependency_edges_df, transactions_df)

    # ============================================================
    # COMPONENT 1: Replacement Cost
    # Cost to replace supplier = 10-30% of annual spend depending on risk
    # ============================================================
    replacement_factor = 0.1 + 0.2 * effective_risk.clip(0.0, 1.0)
    replacement_cost = base_cost * replacement_factor

    # ============================================================
    # COMPONENT 2: Delay Cost
    # Cost of supply chain delays = 5-20% of annual spend, risk-weighted
    # ============================================================
    delay_factor = 0.05 + 0.15 * effective_risk.clip(0.0, 1.0)
    delay_cost = base_cost * delay_factor

    # ============================================================
    # COMPONENT 3: Dependency Exposure Cost
    # Cost from downstream disruption impact
    # = base_cost * dependency_weight * risk, capped at base_cost
    # ============================================================
    raw_dependency = base_cost * dependency_weight * effective_risk.clip(0.0, 1.0)
    dependency_cost = raw_dependency.clip(0.0, base_cost)

    # ============================================================
    # TOTAL COST = R + D + E (absolute value in currency units)
    # Then normalize to [0, 1] for estimated_cost_impact
    # ============================================================
    total_cost_absolute = replacement_cost + delay_cost + dependency_cost

    # Normalize across all suppliers
    if total_cost_absolute.max() > 0:
        out["estimated_cost_impact"] = (total_cost_absolute / total_cost_absolute.max()).clip(0.0, 1.0)
    else:
        out["estimated_cost_impact"] = pd.Series([0.0] * len(out), index=out.index)

    # Store individual components (normalized for readability)
    max_component = total_cost_absolute.max() if total_cost_absolute.max() > 0 else 1.0
    out["replacement_cost"] = (replacement_cost / max_component).clip(0.0, 1.0)
    out["delay_cost"] = (delay_cost / max_component).clip(0.0, 1.0)
    out["dependency_cost"] = (dependency_cost / max_component).clip(0.0, 1.0)
    out["total_cost"] = out["estimated_cost_impact"]  # Normalized total

    # ============================================================
    # COST EXPLANATION: Human-readable breakdown
    # ============================================================
    explanations = []
    for idx in range(len(out)):
        risk_val = float(effective_risk.iloc[idx])
        dep_weight = float(dependency_weight.iloc[idx])
        repl = float(replacement_cost.iloc[idx])
        dlay = float(delay_cost.iloc[idx])
        depe = float(dependency_cost.iloc[idx])

        reasons = []
        if repl > 0:
            reasons.append(
                f"replacement cost ({repl:.0f}) due to risk level {risk_val:.0%}"
            )
        if dlay > 0:
            reasons.append(
                f"delay impact ({dlay:.0f}) from potential supply disruption"
            )
        if depe > 0:
            reasons.append(
                f"downstream exposure ({depe:.0f}) affects {int(dep_weight * 100)}% of network"
            )

        if reasons:
            explanation = "Total cost driven by: " + ", ".join(reasons) + "."
        else:
            explanation = "Low risk supplier with minimal cost impact."

        explanations.append(explanation)

    out["cost_explanation"] = explanations

    # ============================================================
    # CRITICALITY SCORE: Downstream dependencies
    # ============================================================
    if dependency_edges_df.empty or not {"from_company_id", "weight"}.issubset(dependency_edges_df.columns):
        out["criticality_score"] = 0.0
        return out

    edges = dependency_edges_df.copy()
    edges["from_company_id"] = edges["from_company_id"].astype(str)
    edges["to_company_id"] = edges.get("to_company_id", "").astype(str)
    edges["weight"] = pd.to_numeric(edges.get("weight", 0.0), errors="coerce").fillna(0.0).clip(lower=0.0)

    dependents = edges.groupby("from_company_id", dropna=False)["to_company_id"].nunique().rename("dependents")
    avg_strength = edges.groupby("from_company_id", dropna=False)["weight"].mean().rename("avg_strength")

    dependents_val = out["company_id"].map(dependents).fillna(0.0)
    avg_strength_val = out["company_id"].map(avg_strength).fillna(0.0)
    raw_criticality = dependents_val * avg_strength_val

    out["criticality_score"] = _normalize(raw_criticality).clip(0.0, 1.0)

    # ============================================================
    # VALIDATION: Ensure costs are bounded and realistic
    # ============================================================
    assert out["estimated_cost_impact"].max() <= 1.0, "Cost impact exceeds 1.0 after normalization"
    assert out["estimated_cost_impact"].std() > 0.01 or out["estimated_cost_impact"].nunique() == 1, "Cost distribution has no variance"

    return out
