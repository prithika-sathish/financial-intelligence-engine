from __future__ import annotations

import logging
from typing import Any

import networkx as nx
import pandas as pd

LOGGER = logging.getLogger(__name__)


def _company_dependency_edges(transactions_df: pd.DataFrame) -> pd.DataFrame:
    tx = transactions_df.copy()
    tx["amount"] = pd.to_numeric(tx.get("amount", 0.0), errors="coerce").fillna(0.0)

    # Build supplier -> company dependency intensity.
    pair = (
        tx.groupby(["supplier_id", "company_id"], dropna=False)["amount"]
        .sum()
        .reset_index(name="volume")
    )
    if pair.empty:
        return pd.DataFrame(columns=["from_company_id", "to_company_id", "weight", "edge_type"])

    supplier_total = pair.groupby("supplier_id")["volume"].sum().rename("supplier_total")
    pair = pair.merge(supplier_total, on="supplier_id", how="left")
    pair["supplier_dependency_ratio"] = (pair["volume"] / pair["supplier_total"]).fillna(0.0)

    edges: list[dict[str, Any]] = []

    # Shared-supplier contagion between companies.
    for supplier_id, grp in pair.groupby("supplier_id", dropna=False):
        rows = grp.to_dict(orient="records")
        for src in rows:
            for dst in rows:
                if src["company_id"] == dst["company_id"]:
                    continue
                weight = float(dst["supplier_dependency_ratio"] * (src["volume"] / max(src["supplier_total"], 1e-9)))
                edges.append(
                    {
                        "from_company_id": str(src["company_id"]),
                        "to_company_id": str(dst["company_id"]),
                        "weight": weight,
                        "edge_type": "supplier_shared",
                        "supplier_id": supplier_id,
                    }
                )

    # Explicit partner dependencies from transaction columns, if available.
    partner_pairs = [
        ("from_company_id", "to_company_id"),
        ("source_company_id", "target_company_id"),
        ("partner_company_id", "company_id"),
    ]
    for src_col, dst_col in partner_pairs:
        if src_col in tx.columns and dst_col in tx.columns:
            sub = tx[[src_col, dst_col, "amount"]].dropna()
            if not sub.empty:
                agg = sub.groupby([src_col, dst_col], dropna=False)["amount"].sum().reset_index(name="amount")
                total_out = agg.groupby(src_col)["amount"].sum().rename("total_out")
                agg = agg.merge(total_out, on=src_col, how="left")
                for row in agg.to_dict(orient="records"):
                    edges.append(
                        {
                            "from_company_id": str(row[src_col]),
                            "to_company_id": str(row[dst_col]),
                            "weight": float(row["amount"] / max(row["total_out"], 1e-9)),
                            "edge_type": "partner_transaction",
                            "supplier_id": None,
                        }
                    )

    edges_df = pd.DataFrame(edges)
    if edges_df.empty:
        return pd.DataFrame(columns=["from_company_id", "to_company_id", "weight", "edge_type"])

    # Aggregate duplicate edges and cap to avoid explosive propagation.
    edges_df = (
        edges_df.groupby(["from_company_id", "to_company_id", "edge_type"], dropna=False)["weight"]
        .sum()
        .reset_index()
    )
    edges_df["weight"] = edges_df["weight"].clip(lower=0.0, upper=1.0)
    return edges_df


def compute_network_vulnerability_features(transactions_df: pd.DataFrame) -> pd.DataFrame:
    edges_df = _company_dependency_edges(transactions_df)
    if edges_df.empty:
        return pd.DataFrame(
            columns=[
                "company_id",
                "in_degree_risk",
                "supplier_dependency_score",
                "risk_cluster_score",
                "systemic_importance_score",
                "network_exposure_score",
            ]
        )

    graph = nx.DiGraph()
    for row in edges_df.to_dict(orient="records"):
        graph.add_edge(row["from_company_id"], row["to_company_id"], weight=float(row["weight"]))

    pagerank = nx.pagerank(graph, weight="weight") if graph.number_of_nodes() > 0 else {}

    rows: list[dict[str, Any]] = []
    for company in graph.nodes:
        in_w = sum(float(data.get("weight", 0.0)) for _, _, data in graph.in_edges(company, data=True))
        out_w = sum(float(data.get("weight", 0.0)) for _, _, data in graph.out_edges(company, data=True))
        neighbors = set(graph.predecessors(company)).union(set(graph.successors(company)))
        cluster = float(len(neighbors) / max(graph.number_of_nodes(), 1))

        rows.append(
            {
                "company_id": company,
                "in_degree_risk": in_w,
                "supplier_dependency_score": in_w,
                "risk_cluster_score": cluster,
                "systemic_importance_score": float(pagerank.get(company, 0.0)),
                "network_exposure_score": float((0.6 * in_w) + (0.4 * cluster)),
            }
        )

    return pd.DataFrame(rows)


def propagate_dependency_risk(
    base_risk_df: pd.DataFrame,
    transactions_df: pd.DataFrame,
    alpha: float = 0.3,
    max_iter: int = 8,
    tol: float = 1e-5,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    edges_df = _company_dependency_edges(transactions_df)
    base = base_risk_df[["company_id", "risk_score"]].copy()
    base["risk_score"] = pd.to_numeric(base["risk_score"], errors="coerce").fillna(0.0)
    companies = base["company_id"].astype(str).tolist()

    if not companies:
        empty = pd.DataFrame(
            columns=[
                "company_id",
                "base_risk",
                "propagated_risk",
                "network_exposure_score",
                "in_degree_risk",
                "supplier_dependency_score",
                "risk_cluster_score",
                "systemic_importance_score",
                "exposed_companies",
                "dependency_chain",
            ]
        )
        return empty, edges_df

    graph = nx.DiGraph()
    graph.add_nodes_from(companies)
    for row in edges_df.to_dict(orient="records"):
        src = str(row["from_company_id"])
        dst = str(row["to_company_id"])
        if src in companies and dst in companies:
            graph.add_edge(src, dst, weight=float(row["weight"]))

    risk_prev = {row["company_id"]: float(row["risk_score"]) for row in base.to_dict(orient="records")}

    for _ in range(max_iter):
        risk_next = risk_prev.copy()
        max_delta = 0.0
        for node in companies:
            influence = 0.0
            for pred in graph.predecessors(node):
                w = float(graph[pred][node].get("weight", 0.0))
                influence += risk_prev.get(pred, 0.0) * w
            updated = min(max(risk_prev.get(node, 0.0) + alpha * influence, 0.0), 1.0)
            max_delta = max(max_delta, abs(updated - risk_prev.get(node, 0.0)))
            risk_next[node] = updated
        risk_prev = risk_next
        if max_delta < tol:
            break

    pagerank = nx.pagerank(graph, weight="weight") if graph.number_of_nodes() > 0 else {}

    out_rows: list[dict[str, Any]] = []
    for node in companies:
        base_risk = float(base.loc[base["company_id"] == node, "risk_score"].iloc[0])
        propagated = float(risk_prev.get(node, base_risk))
        in_w = sum(float(data.get("weight", 0.0)) for _, _, data in graph.in_edges(node, data=True))
        out_w = sum(float(data.get("weight", 0.0)) for _, _, data in graph.out_edges(node, data=True))
        neighbors = set(graph.predecessors(node)).union(set(graph.successors(node)))
        cluster = float(len(neighbors) / max(graph.number_of_nodes(), 1))
        exposure = max(propagated - base_risk, 0.0)

        incoming = sorted(
            [
                {
                    "company_id": pred,
                    "weight": float(graph[pred][node].get("weight", 0.0)),
                    "risk": float(risk_prev.get(pred, 0.0)),
                }
                for pred in graph.predecessors(node)
            ],
            key=lambda x: x["weight"] * x["risk"],
            reverse=True,
        )
        exposed_companies = [x["company_id"] for x in incoming[:3]]
        dependency_chain = " -> ".join(exposed_companies + [node]) if exposed_companies else node

        out_rows.append(
            {
                "company_id": node,
                "base_risk": base_risk,
                "propagated_risk": propagated,
                "network_exposure_score": float(exposure + (0.2 * in_w)),
                "in_degree_risk": float(in_w),
                "supplier_dependency_score": float(in_w),
                "risk_cluster_score": cluster,
                "systemic_importance_score": float(0.6 * pagerank.get(node, 0.0) + 0.4 * out_w),
                "exposed_companies": exposed_companies,
                "dependency_chain": dependency_chain,
            }
        )

    result_df = pd.DataFrame(out_rows)
    LOGGER.info("Dependency propagation complete for %s companies", len(result_df))
    return result_df, edges_df
