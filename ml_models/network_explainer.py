"""
Network Graph Explainer

Makes the dependency network graph meaningful by:
1. Defining what edges represent (transaction volume dependency)
2. Explaining edge weights (normalized transaction intensity)
3. Computing network centrality metrics
4. Explaining why highly connected nodes are risky
5. Identifying most influential nodes

Network risk principle:
- IN-DEGREE HIGH: Many depend on you; your failure cascades
- OUT-DEGREE HIGH: You depend on many; vulnerable to disruptions
- BETWEENNESS HIGH: You're a bridge; critical for information/supply flow
- CLOSENESS HIGH: You're accessible to all; central in network structure
"""

from __future__ import annotations

import logging
from typing import Any

import networkx as nx
import pandas as pd

from ml_models.explainability import ExplainabilityEngine, NetworkExplanation

LOGGER = logging.getLogger(__name__)


class NetworkGraphExplainer:
    """
    Explains network structure, edges, and risk implications.
    """

    def __init__(self):
        self.explainability_engine = ExplainabilityEngine()

    def get_network_definition(self) -> NetworkExplanation:
        """
        Get explanation of what the network represents.

        Returns:
            NetworkExplanation object
        """
        return self.explainability_engine.explain_network_graph()

    def build_supply_chain_network(
        self,
        transactions_df: pd.DataFrame,
        risk_predictions_df: pd.DataFrame | None = None,
    ) -> nx.DiGraph:
        """
        Build a directed supply chain network from transaction data.

        Nodes = companies
        Edges = company A → company B if A purchases from B
        Edge weight = normalized transaction volume (fraction of A's spending on B)

        Args:
            transactions_df: Transaction data
            risk_predictions_df: Optional risk scores for nodes

        Returns:
            NetworkX DiGraph
        """
        graph = nx.DiGraph()

        # Ensure amount column exists and is numeric
        tx = transactions_df.copy()
        if "amount" not in tx.columns:
            LOGGER.warning("No 'amount' column in transactions. Using unit weights.")
            tx["amount"] = 1.0
        else:
            tx["amount"] = pd.to_numeric(tx["amount"], errors="coerce").fillna(0.0)

        # Required columns
        company_col = (
            "company_id"
            if "company_id" in tx.columns
            else "buyer_id"
            if "buyer_id" in tx.columns
            else None
        )
        supplier_col = (
            "supplier_id"
            if "supplier_id" in tx.columns
            else "seller_id"
            if "seller_id" in tx.columns
            else None
        )

        if company_col is None or supplier_col is None:
            LOGGER.error(
                "Cannot build network: missing company_id/supplier_id columns"
            )
            return graph

        # Compute edge weights: company → supplier
        edges = (
            tx.groupby([company_col, supplier_col], dropna=False)["amount"]
            .sum()
            .reset_index(name="volume")
        )

        # Normalize: weight = volume / total spending by company
        total_by_company = (
            edges.groupby(company_col)["volume"].sum().reset_index(name="total")
        )
        edges = edges.merge(total_by_company, on=company_col, how="left")
        edges["weight"] = (edges["volume"] / edges["total"]).fillna(0.0)
        edges["weight"] = edges["weight"].clip(0.0, 1.0)

        # Add nodes
        all_companies = pd.concat(
            [
                edges[company_col].unique(),
                edges[supplier_col].unique(),
            ]
        )
        for company_id in all_companies:
            company_id_str = str(company_id)
            graph.add_node(company_id_str)

        # Add edges with weights
        for _, row in edges.iterrows():
            src = str(row[company_col])
            dst = str(row[supplier_col])
            weight = float(row["weight"])

            if src and dst and src != dst:
                graph.add_edge(src, dst, weight=weight)

        # Optionally attach risk scores to nodes
        if risk_predictions_df is not None and not risk_predictions_df.empty:
            risk_predictions_df = risk_predictions_df.copy()
            risk_col = (
                "propagated_risk"
                if "propagated_risk" in risk_predictions_df.columns
                else "risk_score"
            )
            risk_predictions_df[risk_col] = pd.to_numeric(
                risk_predictions_df[risk_col], errors="coerce"
            ).fillna(0.0)

            for _, row in risk_predictions_df.iterrows():
                node_id = str(row["company_id"])
                if node_id in graph:
                    graph.nodes[node_id]["risk_score"] = float(row[risk_col])

        LOGGER.info(
            f"Built network: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges"
        )
        return graph

    def compute_all_centrality_metrics(
        self, graph: nx.DiGraph
    ) -> pd.DataFrame:
        """
        Compute comprehensive centrality metrics for all nodes.

        Returns:
            DataFrame with centrality metrics per company
        """
        if graph.number_of_nodes() == 0:
            return pd.DataFrame(
                columns=[
                    "company_id",
                    "degree",
                    "in_degree",
                    "out_degree",
                    "degree_centrality",
                    "in_degree_centrality",
                    "out_degree_centrality",
                    "betweenness_centrality",
                    "closeness_centrality",
                    "pagerank",
                ]
            )

        # Compute metrics
        degree = dict(graph.degree())
        in_degree = dict(graph.in_degree())
        out_degree = dict(graph.out_degree())

        degree_cent = nx.degree_centrality(graph)
        in_degree_cent = nx.in_degree_centrality(graph)
        out_degree_cent = nx.out_degree_centrality(graph)
        betweenness = (
            nx.betweenness_centrality(graph)
            if graph.number_of_nodes() > 1
            else {}
        )
        pagerank = (
            nx.pagerank(graph, weight="weight")
            if graph.number_of_edges() > 0
            else {}
        )

        # Try closeness (may fail on disconnected graphs)
        try:
            closeness = nx.closeness_centrality(graph)
        except Exception:
            closeness = {node: 0.0 for node in graph.nodes()}

        # Build DataFrame
        rows = []
        for node in graph.nodes():
            rows.append(
                {
                    "company_id": node,
                    "degree": int(degree.get(node, 0)),
                    "in_degree": int(in_degree.get(node, 0)),
                    "out_degree": int(out_degree.get(node, 0)),
                    "degree_centrality": float(degree_cent.get(node, 0.0)),
                    "in_degree_centrality": float(in_degree_cent.get(node, 0.0)),
                    "out_degree_centrality": float(out_degree_cent.get(node, 0.0)),
                    "betweenness_centrality": float(betweenness.get(node, 0.0)),
                    "closeness_centrality": float(closeness.get(node, 0.0)),
                    "pagerank": float(pagerank.get(node, 0.0)),
                }
            )

        return pd.DataFrame(rows)

    def compute_node_risk_exposure(
        self, graph: nx.DiGraph, node_id: str
    ) -> dict[str, Any]:
        """
        Compute network-based risk exposure for a single node.

        Considers:
        - IN-DEGREE RISK: How many companies depend on this one failing?
        - OUT-DEGREE RISK: How many suppliers could disrupt this company?
        - BRIDGE RISK: Is this a critical bridge in supply chain?

        Args:
            graph: NetworkX DiGraph
            node_id: Company to analyze

        Returns:
            Dictionary with exposure metrics and explanation
        """
        if node_id not in graph:
            return {
                "company_id": node_id,
                "in_degree_risk": 0.0,
                "out_degree_risk": 0.0,
                "bridge_risk": 0.0,
                "total_exposure": 0.0,
                "explanation": f"Company {node_id} not found in network",
            }

        predecessors = list(graph.predecessors(node_id))  # Who buys from us
        successors = list(graph.successors(node_id))  # Who we buy from

        # IN-DEGREE RISK: normalized by max possible dependents
        in_degree_risk = len(predecessors) / max(1, graph.number_of_nodes() - 1)

        # OUT-DEGREE RISK: normalized by max possible suppliers
        out_degree_risk = len(successors) / max(1, graph.number_of_nodes() - 1)

        # BRIDGE RISK: high betweenness = critical junction
        try:
            betweenness = nx.betweenness_centrality(graph)
            bridge_risk = betweenness.get(node_id, 0.0)
        except Exception:
            bridge_risk = 0.0

        total_exposure = (
            in_degree_risk * 0.4 + out_degree_risk * 0.4 + bridge_risk * 0.2
        )

        if in_degree_risk > 0.3:
            explanation = (
                f"HIGH IN-DEGREE RISK: {len(predecessors)} companies depend on {node_id}. "
                f"Default would trigger cascading failures."
            )
        elif out_degree_risk > 0.3:
            explanation = (
                f"HIGH OUT-DEGREE RISK: {node_id} depends on {len(successors)} suppliers. "
                f"Disruptions to suppliers would directly impact {node_id}."
            )
        elif bridge_risk > 0.3:
            explanation = (
                f"BRIDGE RISK: {node_id} is a critical bridge in supply chain. "
                f"Betweenness centrality: {bridge_risk:.3f}. Position is critical for network connectivity."
            )
        else:
            explanation = (
                f"MODERATE NETWORK RISK: In-degree={len(predecessors)}, Out-degree={len(successors)}, "
                f"Betweenness={bridge_risk:.3f}"
            )

        return {
            "company_id": node_id,
            "in_degree_risk": in_degree_risk,
            "out_degree_risk": out_degree_risk,
            "bridge_risk": bridge_risk,
            "total_exposure": total_exposure,
            "in_degree_count": len(predecessors),
            "out_degree_count": len(successors),
            "explanation": explanation,
        }

    def identify_risk_clusters(
        self, graph: nx.DiGraph
    ) -> dict[str, list[str]]:
        """
        Identify tightly connected clusters/communities in the network.

        Nodes in the same cluster are more likely to experience correlated risk.

        Args:
            graph: NetworkX DiGraph

        Returns:
            Dictionary mapping cluster_id to list of company_ids
        """
        if graph.number_of_nodes() == 0:
            return {}

        # Convert to undirected for community detection
        undirected = graph.to_undirected()

        try:
            from networkx.algorithms import community

            communities = community.greedy_modularity_communities(undirected)
            clusters = {}
            for i, comm in enumerate(communities):
                clusters[f"cluster_{i}"] = sorted([str(node) for node in comm])
            return clusters
        except Exception as e:
            LOGGER.warning(f"Community detection failed: {e}")
            return {}

    def explain_node_in_context(
        self, graph: nx.DiGraph, node_id: str
    ) -> str:
        """
        Generate human-readable explanation of a node's position in network.

        Args:
            graph: NetworkX DiGraph
            node_id: Company to explain

        Returns:
            Plain text explanation
        """
        if node_id not in graph:
            return f"{node_id} is not in the supply chain network."

        exposure = self.compute_node_risk_exposure(graph, node_id)
        in_deg = exposure["in_degree_count"]
        out_deg = exposure["out_degree_count"]

        # Compute centrality
        all_centrality = self.compute_all_centrality_metrics(graph)
        node_centrality = all_centrality[all_centrality["company_id"] == node_id]

        if node_centrality.empty:
            return exposure["explanation"]

        betweenness = float(node_centrality["betweenness_centrality"].iloc[0])

        explanation = (
            f"{node_id}: "
            f"{in_deg} companies depend on it, "
            f"depends on {out_deg} suppliers, "
            f"betweenness={betweenness:.3f}. "
            f"{exposure['explanation']}"
        )

        return explanation
