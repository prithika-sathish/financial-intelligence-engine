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
    """Append estimated_cost_impact and criticality_score to predictions.

    estimated_cost_impact = base_cost * dependency_weight * propagated_risk
    criticality = number_of_dependents * avg_dependency_strength
    Both outputs are normalized to [0, 1].
    """
    if predictions_df.empty:
        out = predictions_df.copy()
        out["estimated_cost_impact"] = []
        out["criticality_score"] = []
        return out

    out = predictions_df.copy()
    out["company_id"] = out["company_id"].astype(str)

    effective_risk = pd.to_numeric(out.get(risk_col, out.get("risk_score", 0.0)), errors="coerce").fillna(0.0)
    base_cost = _compute_base_cost(out["company_id"], transactions_df)
    dependency_weight = _compute_dependency_weight(out["company_id"], dependency_edges_df, transactions_df)

    raw_cost_impact = base_cost * dependency_weight * effective_risk
    out["estimated_cost_impact"] = _normalize(raw_cost_impact).clip(0.0, 1.0)

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
    return out
