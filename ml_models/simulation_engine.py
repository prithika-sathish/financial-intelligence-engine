from __future__ import annotations

import json
from collections import deque
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd


def _build_graph(edges_df: pd.DataFrame) -> tuple[dict[str, list[tuple[str, float]]], dict[str, list[tuple[str, float]]], set[str], dict[tuple[str, str], float]]:
    incoming: dict[str, list[tuple[str, float]]] = defaultdict(list)
    outgoing: dict[str, list[tuple[str, float]]] = defaultdict(list)
    nodes: set[str] = set()
    edge_weights: dict[tuple[str, str], float] = {}

    if edges_df.empty:
        return incoming, outgoing, nodes, edge_weights

    work = edges_df.copy()
    work["from_company_id"] = work["from_company_id"].astype(str)
    work["to_company_id"] = work["to_company_id"].astype(str)
    work["weight"] = pd.to_numeric(work.get("weight", 0.0), errors="coerce").fillna(0.0).clip(lower=0.0, upper=1.0)

    for row in work.to_dict(orient="records"):
        src = row["from_company_id"]
        dst = row["to_company_id"]
        w = float(row["weight"])
        incoming[dst].append((src, w))
        outgoing[src].append((dst, w))
        nodes.add(src)
        nodes.add(dst)
        edge_weights[(src, dst)] = w

    return incoming, outgoing, nodes, edge_weights


def _derive_pair_weight_from_transactions(transactions_df: pd.DataFrame) -> pd.DataFrame:
    if transactions_df.empty:
        return pd.DataFrame(columns=["from_company_id", "to_company_id", "pair_strength"])

    tx = transactions_df.copy()
    tx["amount"] = pd.to_numeric(tx.get("amount", 0.0), errors="coerce").fillna(0.0)

    pair_columns = [
        ("from_company_id", "to_company_id"),
        ("source_company_id", "target_company_id"),
        ("partner_company_id", "company_id"),
    ]

    pair_frames: list[pd.DataFrame] = []
    for src_col, dst_col in pair_columns:
        if src_col in tx.columns and dst_col in tx.columns:
            sub = tx[[src_col, dst_col, "amount"]].dropna().copy()
            if sub.empty:
                continue
            sub[src_col] = sub[src_col].astype(str)
            sub[dst_col] = sub[dst_col].astype(str)
            grouped = sub.groupby([src_col, dst_col], dropna=False).agg(
                volume=("amount", "sum"),
                frequency=("amount", "size"),
            ).reset_index()
            grouped = grouped.rename(columns={src_col: "from_company_id", dst_col: "to_company_id"})

            vol = grouped["volume"]
            freq = grouped["frequency"]
            vol_norm = (vol - vol.min()) / (vol.max() - vol.min() + 1e-8)
            freq_norm = (freq - freq.min()) / (freq.max() - freq.min() + 1e-8)
            grouped["pair_strength"] = 0.7 * vol_norm + 0.3 * freq_norm
            pair_frames.append(grouped[["from_company_id", "to_company_id", "pair_strength"]])

    if not pair_frames:
        return pd.DataFrame(columns=["from_company_id", "to_company_id", "pair_strength"])

    merged = pd.concat(pair_frames, ignore_index=True)
    merged = merged.groupby(["from_company_id", "to_company_id"], dropna=False)["pair_strength"].mean().reset_index()
    merged["pair_strength"] = merged["pair_strength"].clip(0.0, 1.0)
    return merged


def _build_effective_edges(dependency_edges_df: pd.DataFrame, transactions_df: pd.DataFrame) -> pd.DataFrame:
    edges = dependency_edges_df.copy()
    if edges.empty:
        return pd.DataFrame(columns=["from_company_id", "to_company_id", "weight"])

    for col in ["from_company_id", "to_company_id"]:
        edges[col] = edges[col].astype(str)
    edges["weight"] = pd.to_numeric(edges.get("weight", 0.0), errors="coerce").fillna(0.0).clip(lower=0.0, upper=1.0)

    tx_pair = _derive_pair_weight_from_transactions(transactions_df)
    if tx_pair.empty:
        # Derive from observed edge weight distribution when pair-level transactional detail is unavailable.
        ranked = edges["weight"].rank(method="average", pct=True)
        edges["effective_weight"] = (0.6 * edges["weight"] + 0.4 * ranked).clip(0.0, 1.0)
    else:
        edges = edges.merge(tx_pair, on=["from_company_id", "to_company_id"], how="left")
        edges["pair_strength"] = pd.to_numeric(edges.get("pair_strength", 0.0), errors="coerce").fillna(0.0)
        edges["effective_weight"] = (0.65 * edges["weight"] + 0.35 * edges["pair_strength"]).clip(0.0, 1.0)

    aggregated = edges.groupby(["from_company_id", "to_company_id"], dropna=False)["effective_weight"].mean().reset_index()
    aggregated = aggregated.rename(columns={"effective_weight": "weight"})
    return aggregated


def _compute_substitutability(
    incoming: dict[str, list[tuple[str, float]]],
    nodes: set[str],
) -> dict[str, float]:
    in_counts = {node: len(incoming.get(node, [])) for node in nodes}
    max_incoming = max(in_counts.values()) if in_counts else 1

    raw_scores: dict[str, float] = {}
    for node in nodes:
        suppliers = incoming.get(node, [])
        weights = [max(0.0, float(w)) for _, w in suppliers]
        n_suppliers = len(weights)
        alt_count = max(n_suppliers - 1, 0)

        # Option A: alternatives over possible alternatives in this graph.
        option_a = (alt_count / max(1, max_incoming - 1))

        # Option B: inverse burden of missing alternatives (higher alt_count -> higher substitutability).
        option_b = 1.0 - (1.0 / (1.0 + alt_count))

        # Option C: weighted alternative coverage.
        if not weights:
            option_c = 0.0
        else:
            total_weight = float(sum(weights))
            dominant = float(max(weights))
            alt_weight = max(0.0, total_weight - dominant)
            option_c = (alt_weight / total_weight) if total_weight > 1e-9 else 0.0

        raw_scores[node] = float((0.40 * option_a) + (0.25 * option_b) + (0.35 * option_c))

    # Normalize with data-derived range so suppliers separate when graph structure supports it.
    values = np.array(list(raw_scores.values()), dtype=float) if raw_scores else np.array([], dtype=float)
    if len(values) == 0:
        return {}
    vmin = float(values.min())
    vmax = float(values.max())
    if vmax - vmin <= 1e-9:
        return {k: float(np.clip(v, 0.0, 1.0)) for k, v in raw_scores.items()}

    return {
        k: float(np.clip((v - vmin) / (vmax - vmin), 0.0, 1.0))
        for k, v in raw_scores.items()
    }


def _company_delay_baseline(transactions_df: pd.DataFrame) -> dict[str, float]:
    """Extract median inter-transaction time (days) per company from transaction timestamps.
    
    Returns empty dict if timestamps unavailable—fallback delay calculation will be used.
    """
    if transactions_df.empty or "company_id" not in transactions_df.columns:
        return {}
    if "timestamp" not in transactions_df.columns:
        return {}

    tx = transactions_df.copy()
    tx["company_id"] = tx["company_id"].astype(str)
    tx["timestamp"] = pd.to_datetime(tx["timestamp"], errors="coerce", utc=True)
    tx = tx.dropna(subset=["timestamp"])
    if tx.empty:
        return {}

    result: dict[str, float] = {}
    for company, grp in tx.groupby("company_id", dropna=False):
        ordered = grp.sort_values("timestamp")["timestamp"]
        if len(ordered) < 2:
            continue
        diffs = ordered.diff().dropna().dt.total_seconds() / 86400.0
        diffs = diffs[diffs > 0]
        if diffs.empty:
            continue
        result[str(company)] = float(np.median(diffs))
    return result


def _estimate_delay_from_network(
    node_min_level: dict[str, int],
    impact_map: dict[str, float],
    total_impact_score: float,
) -> float:
    """Estimate propagation delay when transaction-level timestamps are unavailable.
    
    Uses network depth (level) as proxy: each level adds ~3-5 days for reordering lag.
    Combined with impact concentration to estimate order fulfillment disruption.
    """
    if not impact_map or total_impact_score <= 0.0:
        return 1.0  # Minimum fallback: 1 day
    
    # Average network level of impacted suppliers
    levels = [float(node_min_level.get(node, 3)) for node in impact_map.keys()]
    avg_level = float(np.mean(levels)) if levels else 2.0
    
    # Level-based delay: more levels = more supply chain complexity
    # Level 1 (direct): 2–3 days
    # Level 2 (indirect): 4–6 days  
    # Level 3+ (deep): 7+ days
    level_delay = 2.0 + (avg_level - 1.0) * 2.5
    
    # Impact concentration scaling: high concentration = higher delay
    # because substitute sourcing is limited
    impact_values = np.array([float(v) for v in impact_map.values()])
    total_impact = float(impact_values.sum())
    if total_impact > 0:
        hhi = float(np.sum((impact_values / total_impact) ** 2))
        concentration_factor = 1.0 + (hhi - 0.5) * 0.5  # [1.0, 1.25] range
    else:
        concentration_factor = 1.0
    
    estimated_delay = level_delay * concentration_factor
    return float(np.clip(estimated_delay, 1.0, 14.0))


def _decay_factor(level: int) -> float:
    if level == 1:
        return 1.0
    if level == 2:
        return 0.6
    if level == 3:
        return 0.3
    return 0.0


def _iterative_propagation(
    base_risk: dict[str, float],
    incoming: dict[str, list[tuple[str, float]]],
    nodes: set[str],
    alpha: float = 0.4,
    beta: float = 0.3,
    max_iter: int = 3,
) -> dict[str, float]:
    risk_prev = {node: float(base_risk.get(node, 0.0)) for node in nodes}

    for _ in range(max(1, max_iter)):
        next_risk = risk_prev.copy()
        for node in nodes:
            preds = incoming.get(node, [])
            influence = 0.0
            for pred, w in preds:
                influence += risk_prev.get(pred, 0.0) * float(w)
            influence = alpha * (influence / (len(preds) + 1e-6))
            base = float(base_risk.get(node, 0.0))
            next_risk[node] = float(max(0.0, min(1.0, (1.0 - beta) * base + beta * influence)))
        risk_prev = next_risk

    return risk_prev


def _raw_cost_map(transactions_df: pd.DataFrame, risks: dict[str, float], outgoing: dict[str, list[tuple[str, float]]]) -> dict[str, float]:
    tx = transactions_df.copy()
    if "company_id" not in tx.columns:
        return {node: 0.0 for node in risks}

    tx["amount"] = pd.to_numeric(tx.get("amount", 0.0), errors="coerce").fillna(0.0)
    base_cost = tx.groupby("company_id", dropna=False)["amount"].sum().to_dict()

    out: dict[str, float] = {}
    for node, risk in risks.items():
        deps = outgoing.get(node, [])
        avg_dep_weight = sum(w for _, w in deps) / max(len(deps), 1)
        out[node] = float(base_cost.get(node, 0.0)) * float(avg_dep_weight) * float(risk)
    return out


def _base_cost_map(transactions_df: pd.DataFrame) -> dict[str, float]:
    tx = transactions_df.copy()
    if "company_id" not in tx.columns:
        return {}
    tx["amount"] = pd.to_numeric(tx.get("amount", 0.0), errors="coerce").fillna(0.0)
    return tx.groupby("company_id", dropna=False)["amount"].sum().to_dict()


def simulate_failure(
    node: str,
    predictions_df: pd.DataFrame,
    dependency_edges_df: pd.DataFrame,
    transactions_df: pd.DataFrame,
) -> tuple[list[dict[str, Any]], float, float, float, str]:
    """Simulate supplier failure with weighted, substitutability-aware, depth-decayed propagation."""
    if predictions_df.empty:
        return [], 0.0, float("nan"), float("nan"), "Data unavailable"

    pred = predictions_df.copy()
    pred["company_id"] = pred["company_id"].astype(str)
    node = str(node)

    effective_edges = _build_effective_edges(dependency_edges_df, transactions_df)
    incoming, outgoing, nodes, edge_weights = _build_graph(effective_edges)
    nodes.update(pred["company_id"].astype(str).tolist())
    substitutability = _compute_substitutability(incoming, nodes)

    risk_map = pd.Series(
        pd.to_numeric(pred.get("propagated_risk", pred.get("risk_score", 0.0)), errors="coerce").fillna(0.0).values,
        index=pred["company_id"],
    ).to_dict()
    source_risk = float(risk_map.get(node, 0.0))
    source_risk = float(np.clip(source_risk, 0.0, 0.95))

    if node not in nodes or source_risk <= 0.0:
        return [], 0.0, float("nan"), float("nan"), "Data unavailable"

    in_degree = {n: len(incoming.get(n, [])) for n in nodes}
    in_degrees = pd.Series(list(in_degree.values()), dtype=float)
    degree_q75 = float(in_degrees.quantile(0.75)) if not in_degrees.empty else 0.0
    subst_median = float(pd.Series(list(substitutability.values()), dtype=float).median()) if substitutability else 0.0

    frontier: dict[str, float] = {node: 1.0}
    impact_map: dict[str, float] = defaultdict(float)
    node_min_level: dict[str, int] = {}
    node_max_edge_weight: dict[str, float] = defaultdict(float)

    for level in range(1, 4):
        decay = _decay_factor(level)
        if decay <= 0.0:
            break
        next_frontier: dict[str, float] = defaultdict(float)
        for current, current_strength in frontier.items():
            for neighbor, edge_weight in outgoing.get(current, []):
                edge_weight = float(np.clip(edge_weight, 0.0, 1.0))
                node_sub = float(np.clip(substitutability.get(neighbor, 0.0), 0.0, 1.0))
                base_impact = edge_weight * (1.0 - node_sub)
                if base_impact <= 0.0:
                    continue
                propagated_component = float(current_strength) * base_impact
                if propagated_component <= 0.0:
                    continue

                next_frontier[neighbor] += propagated_component
                impact_map[neighbor] += source_risk * decay * propagated_component
                node_max_edge_weight[neighbor] = max(node_max_edge_weight[neighbor], edge_weight)
                if neighbor not in node_min_level or level < node_min_level[neighbor]:
                    node_min_level[neighbor] = level
        frontier = next_frontier

    if node in impact_map:
        impact_map.pop(node, None)

    impact_vals = np.array([float(v) for v in impact_map.values()], dtype=float) if impact_map else np.array([], dtype=float)
    if len(impact_vals) <= 1 or float(impact_vals.mean()) <= 1e-12:
        validation_note = "Impact distribution unavailable"
    else:
        cv = float(impact_vals.std() / (impact_vals.mean() + 1e-12))
        validation_note = (
            f"Impact distribution variance confirmed (CV={cv:.3f})"
            if cv >= 0.10
            else f"Low impact variance observed (CV={cv:.3f}); review edge diversity and alternatives"
        )

    base_cost = _base_cost_map(transactions_df)
    total_spend = float(sum(base_cost.values()))
    delay_baseline = _company_delay_baseline(transactions_df)

    impacted_rows: list[dict[str, Any]] = []
    weighted_delay_numer = 0.0
    weighted_delay_denom = 0.0

    for affected, score in impact_map.items():
        score = float(max(0.0, score))
        if score <= 1e-10:
            continue

        level = node_min_level.get(affected, 3)
        dep_type = "direct" if level == 1 else "indirect"
        edge_w = float(node_max_edge_weight.get(affected, edge_weights.get((node, affected), 0.0)))
        sub = float(np.clip(substitutability.get(affected, 0.0), 0.0, 1.0))

        reasons: list[str] = []
        if sub <= 0.35:
            reasons.append(
                f"High dependency ({edge_w:.2f}) with limited alternatives raises disruption exposure"
            )
        else:
            reasons.append(
                f"Dependency remains material ({edge_w:.2f}), but available alternatives partially absorb the shock"
            )
        reasons.append(
            "Direct dependency amplifies immediate impact" if level == 1 else "Indirect dependency transmits risk through upstream links"
        )
        reasons.append(f"Source supplier risk ({source_risk:.2f}) increases propagation pressure")
        if in_degree.get(affected, 0) >= degree_q75 and sub >= subst_median:
            reasons.append(
                "Multiple inbound links provide mitigation capacity despite high connectivity"
            )
        if score >= np.percentile(np.array(list(impact_map.values()), dtype=float), 85):
            reasons.append("This supplier is in the top impact tier and should be prioritized")

        impacted_rows.append(
            {
                "name": affected,
                "impact_score": score,
                "type": dep_type,
                "reasons": reasons,
            }
        )

        if affected in delay_baseline:
            weighted_delay_numer += float(delay_baseline[affected]) * score
            weighted_delay_denom += score

    impacted_rows.sort(key=lambda x: float(x.get("impact_score", 0.0)), reverse=True)
    total_impact_score = float(sum(float(row.get("impact_score", 0.0)) for row in impacted_rows))

    potential_cost_increase = float(
        sum(float(base_cost.get(row["name"], 0.0)) * float(row.get("impact_score", 0.0)) for row in impacted_rows)
    )
    cost_increase_percent = (100.0 * potential_cost_increase / total_spend) if total_spend > 0 else float("nan")

    # Calculate delay: prioritize transaction-based delay, fallback to network-based estimate
    if weighted_delay_denom > 0:
        # Actual transaction data available
        baseline_delay = weighted_delay_numer / weighted_delay_denom
        delay_days = baseline_delay * (1.0 + min(1.0, total_impact_score))
    else:
        # Fallback: estimate from network propagation depth and impact concentration
        delay_days = _estimate_delay_from_network(node_min_level, impact_map, total_impact_score)

    return impacted_rows, total_impact_score, delay_days, cost_increase_percent, validation_note


def _neighbor_sets(edges_df: pd.DataFrame) -> dict[str, set[str]]:
    neighbor_map: dict[str, set[str]] = defaultdict(set)
    if edges_df.empty:
        return neighbor_map

    work = edges_df.copy()
    work["from_company_id"] = work["from_company_id"].astype(str)
    work["to_company_id"] = work["to_company_id"].astype(str)

    for row in work.to_dict(orient="records"):
        src = row["from_company_id"]
        dst = row["to_company_id"]
        neighbor_map[src].add(dst)
        neighbor_map[dst].add(src)

    return neighbor_map


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return float(len(a.intersection(b)) / max(1, len(a.union(b))))


def _suggest_alternatives(
    failed_node: str,
    out_df: pd.DataFrame,
    dependency_edges_df: pd.DataFrame,
    substitutability: dict[str, float],
    top_k: int,
) -> str:
    company_list = out_df["company_id"].astype(str).tolist()
    risk_map = pd.Series(
        pd.to_numeric(out_df.get("propagated_risk", out_df.get("risk_score", 0.0)), errors="coerce").fillna(0.0).values,
        index=out_df["company_id"].astype(str),
    ).to_dict()

    neighbor_map = _neighbor_sets(dependency_edges_df)
    target_neighbors = neighbor_map.get(failed_node, set())
    median_risk = float(np.median(list(risk_map.values()))) if risk_map else 0.0

    candidates: list[tuple[str, float, float, float]] = []
    for cand in company_list:
        if cand == failed_node:
            continue
        cand_risk = float(risk_map.get(cand, 0.0))
        cand_sub = float(substitutability.get(cand, 0.0))
        if cand_risk > median_risk:
            continue
        sim = _jaccard(target_neighbors, neighbor_map.get(cand, set()))
        candidates.append((cand, sim, cand_sub, cand_risk))

    candidates.sort(key=lambda x: (-x[1], -x[2], x[3], x[0]))
    top = [c[0] for c in candidates[: max(2, top_k)]]
    return "|".join(top)


def run_supplier_failure_simulations(
    predictions_df: pd.DataFrame,
    dependency_edges_df: pd.DataFrame,
    transactions_df: pd.DataFrame,
    top_k_alternatives: int = 3,
) -> pd.DataFrame:
    """Append explainable weighted failure simulation outputs."""
    out = predictions_df.copy()
    if out.empty:
        out["potential_impact_nodes"] = []
        out["potential_cost_increase"] = []
        out["affected_suppliers"] = []
        out["total_impact_score"] = []
        out["delay_days"] = []
        out["cost_increase_percent"] = []
        out["impact_validation_note"] = []
        out["suggested_alternatives"] = []
        return out

    out["company_id"] = out["company_id"].astype(str)
    impact_nodes_col: list[list[str]] = []
    cost_increase_col: list[float] = []
    affected_suppliers_col: list[str] = []
    total_impact_col: list[float] = []
    delay_days_col: list[float] = []
    cost_increase_pct_col: list[float] = []
    validation_col: list[str] = []
    alternatives_col: list[str] = []

    effective_edges = _build_effective_edges(dependency_edges_df, transactions_df)
    incoming, _, nodes, _ = _build_graph(effective_edges)
    nodes.update(out["company_id"].astype(str).tolist())
    substitutability = _compute_substitutability(incoming, nodes)

    company_list = out["company_id"].tolist()
    for node in company_list:
        impacted_rows, total_impact_score, delay_days, cost_increase_pct, validation_note = simulate_failure(
            node,
            out,
            effective_edges,
            transactions_df,
        )
        impact_nodes_col.append([str(row.get("name")) for row in impacted_rows])
        affected_suppliers_col.append(json.dumps(impacted_rows, ensure_ascii=True))
        total_impact_col.append(float(total_impact_score))
        delay_days_col.append(float(delay_days) if pd.notna(delay_days) else np.nan)
        cost_increase_pct_col.append(float(cost_increase_pct) if pd.notna(cost_increase_pct) else np.nan)
        validation_col.append(validation_note)

        base_cost = _base_cost_map(transactions_df)
        potential_cost_increase = float(
            sum(float(base_cost.get(row.get("name"), 0.0)) * float(row.get("impact_score", 0.0)) for row in impacted_rows)
        )
        cost_increase_col.append(potential_cost_increase)

        alternatives_col.append(
            _suggest_alternatives(
                failed_node=node,
                out_df=out,
                dependency_edges_df=effective_edges,
                substitutability=substitutability,
                top_k=top_k_alternatives,
            )
        )

    out["potential_impact_nodes"] = impact_nodes_col
    out["potential_cost_increase"] = cost_increase_col
    out["affected_suppliers"] = affected_suppliers_col
    out["total_impact_score"] = total_impact_col
    out["delay_days"] = delay_days_col
    out["cost_increase_percent"] = cost_increase_pct_col
    out["impact_validation_note"] = validation_col
    out["suggested_alternatives"] = alternatives_col
    return out
