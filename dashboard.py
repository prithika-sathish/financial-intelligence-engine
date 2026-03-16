from __future__ import annotations

import ast
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from configs.settings import get_settings
try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency at runtime
    load_dotenv = None

try:
    from langchain.prompts import ChatPromptTemplate
except Exception:  # pragma: no cover - optional dependency at runtime
    ChatPromptTemplate = None

try:
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover - optional dependency at runtime
    plt = None

try:
    from langchain_groq import ChatGroq
except Exception:  # pragma: no cover - optional dependency at runtime
    ChatGroq = None

try:
    from pyvis.network import Network
except Exception:  # pragma: no cover - optional dependency at runtime
    Network = None

try:
    from transformers import pipeline
except Exception:  # pragma: no cover - optional dependency at runtime
    pipeline = None

APP_TITLE = "Financial Intelligence Platform"
APP_SUBTITLE = "Interactive analytics for exposure, anomalies, contagion, and explainable AI insights"

RISK_LOW_THRESHOLD = 0.40
RISK_HIGH_THRESHOLD = 0.75

ROOT = Path(__file__).resolve().parent
OUTPUTS_DIR = ROOT / "outputs"
SAMPLE_TRANSACTIONS_PATH = ROOT / "sample_data" / "sample_transactions.json"


def _load_environment() -> None:
    # Streamlit sessions may not inherit shell-exported variables; load from local .env when available.
    if load_dotenv is not None:
        load_dotenv(dotenv_path=ROOT / ".env", override=False)
        return

    env_path = ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _apply_theme() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide", initial_sidebar_state="expanded")
    st.markdown(
        """
        <style>
            :root {
                --bg-main: #0b1220;
                --bg-panel: #131c2e;
                --bg-panel-soft: #18243b;
                --text-main: #e6edf7;
                --text-muted: #9fb0cf;
                --accent: #22c1aa;
                --danger: #ef4444;
                --warning: #f59e0b;
                --ok: #10b981;
            }

            .stApp {
                background:
                    radial-gradient(circle at 15% 15%, rgba(34,193,170,0.15), transparent 35%),
                    radial-gradient(circle at 85% 10%, rgba(52,121,255,0.12), transparent 35%),
                    linear-gradient(180deg, #0a1020 0%, #0b1220 100%);
                color: var(--text-main);
            }

            .block-container {
                padding-top: 1.2rem;
                padding-bottom: 2rem;
            }

            h1, h2, h3 {
                color: var(--text-main) !important;
                letter-spacing: 0.2px;
            }

            .hero {
                background: linear-gradient(120deg, rgba(34,193,170,0.14), rgba(52,121,255,0.08));
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 16px;
                padding: 18px 20px;
                margin-bottom: 14px;
            }

            .small-note {
                color: var(--text-muted);
                font-size: 0.92rem;
            }

            div[data-testid="stMetric"] {
                background: var(--bg-panel);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 12px;
                padding: 8px;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def load_data() -> dict[str, pd.DataFrame]:
    data = {
        "anomaly": _load_csv(OUTPUTS_DIR / "anomaly_scores.csv"),
        "entities": _load_csv(OUTPUTS_DIR / "entities.csv"),
        "events": _load_csv(OUTPUTS_DIR / "events.csv"),
        "features": _load_csv(OUTPUTS_DIR / "features.csv"),
        "predictions": _load_csv(OUTPUTS_DIR / "risk_predictions.csv"),
        "trends": _load_csv(OUTPUTS_DIR / "risk_trends.csv"),
        "network": _load_csv(OUTPUTS_DIR / "network_risk_analysis.csv"),
    }

    # Optional JSON outputs for richer context and UI.
    risk_trends_json = _load_json(OUTPUTS_DIR / "risk_trends.json")
    network_json = _load_json(OUTPUTS_DIR / "network_risk_analysis.json")
    data["risk_trends_json"] = pd.DataFrame(risk_trends_json or [])
    data["network_json"] = pd.DataFrame(network_json or [])

    # Optional source transaction details for amount/company filtering in anomaly views.
    tx_records = _load_json(SAMPLE_TRANSACTIONS_PATH)
    data["transactions_sample"] = pd.DataFrame(tx_records or [])

    return data


def _risk_level_from_score(score: float) -> str:
    if score >= RISK_HIGH_THRESHOLD:
        return "high"
    if score >= RISK_LOW_THRESHOLD:
        return "medium"
    return "low"


def _risk_color(score: float) -> str:
    if score >= RISK_HIGH_THRESHOLD:
        return "#ef4444"
    if score >= RISK_LOW_THRESHOLD:
        return "#f59e0b"
    return "#10b981"


def _safe_literal(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
            return parsed
        except Exception:
            return default
    return default


def _ensure_datetime(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    return df


def _render_overview_section(data: dict[str, pd.DataFrame]) -> None:
    st.header("Section 1 - System Overview")

    pred = data["predictions"].copy()
    anom = data["anomaly"].copy()
    events = data["events"].copy()

    total_companies = int(pred["company_id"].nunique()) if "company_id" in pred.columns else 0
    total_transactions = int(len(anom))
    total_events = int(len(events))
    total_anomalies = int(pd.to_numeric(anom.get("anomaly_flag", 0), errors="coerce").fillna(0).sum())
    anomaly_rate = (total_anomalies / total_transactions) if total_transactions else 0.0

    alert_proxy = 0
    if not pred.empty:
        risk_col = "propagated_risk" if "propagated_risk" in pred.columns else "risk_score"
        alert_proxy = int((pd.to_numeric(pred[risk_col], errors="coerce").fillna(0) >= RISK_LOW_THRESHOLD).sum())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Companies", total_companies, help="Unique companies in risk_predictions.csv")
    c2.metric("Transactions Processed", total_transactions, help="Rows in anomaly_scores.csv")
    c3.metric("Events Detected", total_events, help="Rows in events.csv")
    c4.metric("Anomaly Rate", f"{anomaly_rate:.2%}", help="Detected anomalies / processed transactions")
    c5.metric("Total Alerts Generated", alert_proxy, help="Proxy alert count: companies with medium/high propagated risk")

    st.caption("Dashboard reads only from outputs files; no ML pipeline stages are executed here.")


def _render_leaderboard_section(data: dict[str, pd.DataFrame]) -> None:
    st.header("Section 2 - Company Risk Leaderboard")
    pred = data["predictions"].copy()

    if pred.empty:
        st.warning("risk_predictions.csv not found or empty.")
        return

    required_cols = [
        "company_id",
        "risk_score",
        "risk_level",
        "propagated_risk",
        "network_exposure_score",
        "systemic_importance_score",
    ]
    for col in required_cols:
        if col not in pred.columns:
            pred[col] = np.nan

    risk_plot_col = "propagated_risk" if pred["propagated_risk"].notna().any() else "risk_score"
    pred[risk_plot_col] = pd.to_numeric(pred[risk_plot_col], errors="coerce").fillna(0.0)

    ranked = pred.sort_values(risk_plot_col, ascending=False)

    c1, c2 = st.columns([1.25, 1])
    with c1:
        fig_rank = px.bar(
            ranked,
            x="company_id",
            y=risk_plot_col,
            color=risk_plot_col,
            color_continuous_scale=["#10b981", "#f59e0b", "#ef4444"],
            title="Risk Ranking by Company",
            text_auto=".2f",
        )
        fig_rank.update_layout(template="plotly_dark", xaxis_title="Company", yaxis_title="Risk Score")
        st.plotly_chart(fig_rank, use_container_width=True)

    with c2:
        fig_hist = px.histogram(
            pred,
            x=risk_plot_col,
            nbins=12,
            color_discrete_sequence=["#22c1aa"],
            title="Risk Score Distribution",
        )
        fig_hist.update_layout(template="plotly_dark", xaxis_title="Risk Score", yaxis_title="Count")
        st.plotly_chart(fig_hist, use_container_width=True)

    st.dataframe(
        ranked[required_cols],
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Bonus: Risk Heatmap"):
        heat_cols = [
            c
            for c in ["risk_score", "propagated_risk", "network_exposure_score", "systemic_importance_score"]
            if c in ranked.columns
        ]
        if heat_cols:
            mat = ranked.set_index("company_id")[heat_cols].fillna(0.0)
            fig_heat = px.imshow(
                mat,
                color_continuous_scale="RdYlGn_r",
                aspect="auto",
                title="Company Risk Feature Heatmap",
            )
            fig_heat.update_layout(template="plotly_dark")
            st.plotly_chart(fig_heat, use_container_width=True)
        else:
            st.info("No numeric risk columns available for heatmap.")


def _expand_risk_history(trends: pd.DataFrame) -> pd.DataFrame:
    if trends.empty or "risk_history" not in trends.columns:
        return pd.DataFrame(columns=["company_id", "t", "risk"])

    rows: list[dict[str, Any]] = []
    for _, row in trends.iterrows():
        hist = _safe_literal(row.get("risk_history"), [])
        if not isinstance(hist, list):
            continue
        for idx, val in enumerate(hist):
            rows.append(
                {
                    "company_id": row.get("company_id"),
                    "t": idx,
                    "risk": float(val) if pd.notna(val) else 0.0,
                }
            )
    return pd.DataFrame(rows)


def _render_trends_section(data: dict[str, pd.DataFrame]) -> None:
    st.header("Section 3 - Risk Trend Visualization")
    trends = data["trends"].copy()

    if trends.empty:
        st.warning("risk_trends.csv not found or empty.")
        return

    for col in ["risk_velocity", "risk_acceleration"]:
        if col not in trends.columns:
            trends[col] = 0.0
        trends[col] = pd.to_numeric(trends[col], errors="coerce").fillna(0.0)

    companies = sorted(trends["company_id"].dropna().astype(str).unique().tolist())
    selected = st.selectbox("Select company", companies) if companies else None

    hist_df = _expand_risk_history(trends)
    if selected and not hist_df.empty:
        company_hist = hist_df[hist_df["company_id"] == selected]
    else:
        company_hist = hist_df

    c1, c2 = st.columns([1.5, 1])
    with c1:
        if not company_hist.empty:
            fig_line = px.line(
                company_hist,
                x="t",
                y="risk",
                color="company_id",
                markers=True,
                title="Risk History Evolution",
            )
            fig_line.update_layout(template="plotly_dark", xaxis_title="Time Index", yaxis_title="Risk")
            st.plotly_chart(fig_line, use_container_width=True)
        else:
            st.info("No risk_history points available.")

    with c2:
        slope_df = trends[["company_id", "risk_velocity", "risk_acceleration"]].copy()
        fig_slope = px.bar(
            slope_df,
            x="company_id",
            y="risk_velocity",
            color="risk_velocity",
            title="Trend Slope (Velocity)",
            color_continuous_scale="RdYlGn_r",
        )
        fig_slope.update_layout(template="plotly_dark")
        st.plotly_chart(fig_slope, use_container_width=True)

    fig_scatter = px.scatter(
        trends,
        x="risk_velocity",
        y="risk_acceleration",
        size=np.abs(trends["risk_velocity"]).clip(lower=0.02),
        hover_name="company_id",
        color="risk_trend" if "risk_trend" in trends.columns else None,
        title="Velocity vs Acceleration",
    )
    fig_scatter.update_layout(template="plotly_dark")
    st.plotly_chart(fig_scatter, use_container_width=True)


def _build_dependency_graph(network_df: pd.DataFrame) -> nx.DiGraph:
    g = nx.DiGraph()
    if network_df.empty:
        return g

    for _, row in network_df.iterrows():
        cid = str(row.get("company_id"))
        prop_risk = float(pd.to_numeric(row.get("propagated_risk", 0.0), errors="coerce") or 0.0)
        systemic = float(pd.to_numeric(row.get("systemic_importance_score", 0.0), errors="coerce") or 0.0)
        g.add_node(
            cid,
            propagated_risk=prop_risk,
            base_risk=float(pd.to_numeric(row.get("base_risk", 0.0), errors="coerce") or 0.0),
            network_exposure=float(pd.to_numeric(row.get("network_exposure_score", 0.0), errors="coerce") or 0.0),
            systemic_importance=systemic,
            risk_level=_risk_level_from_score(prop_risk),
        )

        dep_chain = str(row.get("dependency_chain", "")).strip()
        if "->" in dep_chain:
            parts = [p.strip() for p in dep_chain.split("->") if p.strip()]
            for src, dst in zip(parts[:-1], parts[1:]):
                if src != dst:
                    g.add_edge(src, dst, weight=max(0.1, float(row.get("network_exposure_score", 0.1) or 0.1)))

        exposed = _safe_literal(row.get("exposed_companies"), [])
        if isinstance(exposed, list):
            for target in exposed:
                target_id = str(target)
                if target_id and target_id != cid and not g.has_edge(cid, target_id):
                    g.add_edge(cid, target_id, weight=max(0.05, float(row.get("network_exposure_score", 0.1) or 0.1)))

    return g


def _render_pyvis_graph(graph: nx.DiGraph) -> None:
    if Network is None:
        st.warning("pyvis is not available. Install pyvis to enable interactive dependency network rendering.")
        return
    if graph.number_of_nodes() == 0:
        st.info("No network nodes available.")
        return

    net = Network(height="640px", width="100%", directed=True, bgcolor="#0f172a", font_color="#e5e7eb")
    net.barnes_hut(gravity=-40000, central_gravity=0.2, spring_length=140, spring_strength=0.02, damping=0.9)

    for node, attrs in graph.nodes(data=True):
        risk = float(attrs.get("propagated_risk", 0.0))
        systemic = float(attrs.get("systemic_importance", 0.0))
        size = 18 + (systemic * 90)
        color = _risk_color(risk)
        title = (
            f"Company: {node}<br>"
            f"Risk: {risk:.3f}<br>"
            f"Risk Level: {attrs.get('risk_level', 'low')}<br>"
            f"Network Exposure: {float(attrs.get('network_exposure', 0.0)):.3f}<br>"
            f"Systemic Importance: {systemic:.3f}"
        )
        net.add_node(node, label=node, size=size, color=color, title=title)

    for src, dst, attrs in graph.edges(data=True):
        weight = float(attrs.get("weight", 0.1))
        net.add_edge(src, dst, value=max(1.0, weight * 10.0), title=f"Propagation weight: {weight:.3f}")

    net.set_options(
        """
        {
          "interaction": {
            "hover": true,
            "navigationButtons": true,
            "keyboard": true
          },
          "physics": {
            "enabled": true
          }
        }
        """
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as tmp:
        net.save_graph(tmp.name)
        html = Path(tmp.name).read_text(encoding="utf-8")
    st.components.v1.html(html, height=660, scrolling=True)


def _render_network_section(data: dict[str, pd.DataFrame]) -> nx.DiGraph:
    st.header("Section 4 - Dependency Network Graph")
    network = data["network"].copy()
    if network.empty:
        network = data["network_json"].copy()

    if network.empty:
        st.warning("network_risk_analysis.csv/json not found or empty.")
        return nx.DiGraph()

    for col in ["base_risk", "propagated_risk", "network_exposure_score", "systemic_importance_score"]:
        if col not in network.columns:
            network[col] = 0.0

    graph = _build_dependency_graph(network)
    _render_pyvis_graph(graph)

    with st.expander("Risk propagation paths"):
        if "dependency_chain" in network.columns:
            paths = network[["company_id", "dependency_chain", "network_exposure_score"]].copy()
            st.dataframe(paths, use_container_width=True, hide_index=True)
        else:
            st.info("No dependency_chain column available in network output.")

    return graph


def _render_anomaly_section(data: dict[str, pd.DataFrame]) -> None:
    st.header("Section 5 - Transaction Anomaly Insights")
    anom = data["anomaly"].copy()
    tx = data["transactions_sample"].copy()

    if anom.empty:
        st.warning("anomaly_scores.csv not found or empty.")
        return

    anom["anomaly_score"] = pd.to_numeric(anom.get("anomaly_score", 0.0), errors="coerce").fillna(0.0)
    anom["anomaly_flag"] = pd.to_numeric(anom.get("anomaly_flag", 0), errors="coerce").fillna(0).astype(int)

    if not tx.empty and "transaction_id" in tx.columns:
        merged = anom.merge(tx, on="transaction_id", how="left")
    else:
        merged = anom.copy()

    companies = ["ALL"]
    if "company_id" in merged.columns:
        companies += sorted(merged["company_id"].dropna().astype(str).unique().tolist())
    selected = st.selectbox("Filter by company", companies)

    if selected != "ALL" and "company_id" in merged.columns:
        merged = merged[merged["company_id"] == selected]

    c1, c2 = st.columns([1, 1])
    with c1:
        fig_hist = px.histogram(
            merged,
            x="anomaly_score",
            nbins=18,
            color="anomaly_flag",
            title="Anomaly Score Histogram",
            color_discrete_map={0: "#22c1aa", 1: "#ef4444"},
        )
        fig_hist.update_layout(template="plotly_dark")
        st.plotly_chart(fig_hist, use_container_width=True)

    with c2:
        if "amount" in merged.columns:
            merged["amount"] = pd.to_numeric(merged["amount"], errors="coerce").fillna(0.0)
            fig_scatter = px.scatter(
                merged,
                x="amount",
                y="anomaly_score",
                color="anomaly_flag",
                hover_data=[c for c in ["transaction_id", "company_id", "supplier_id", "timestamp"] if c in merged.columns],
                title="Anomaly Score vs Transaction Amount",
                color_discrete_map={0: "#22c1aa", 1: "#ef4444"},
            )
            fig_scatter.update_layout(template="plotly_dark")
            st.plotly_chart(fig_scatter, use_container_width=True)
        else:
            fig_rank = px.bar(
                merged.sort_values("anomaly_score", ascending=False).head(15),
                x="transaction_id",
                y="anomaly_score",
                title="Top Transaction Anomaly Scores",
                color="anomaly_score",
                color_continuous_scale="RdYlGn_r",
            )
            fig_rank.update_layout(template="plotly_dark")
            st.plotly_chart(fig_rank, use_container_width=True)

    top_cols = [c for c in ["transaction_id", "company_id", "supplier_id", "amount", "anomaly_score", "anomaly_flag", "timestamp"] if c in merged.columns]
    st.subheader("Top Anomalous Transactions")
    st.dataframe(
        merged.sort_values("anomaly_score", ascending=False)[top_cols].head(20),
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Bonus: Anomaly Timeline"):
        if "timestamp" in merged.columns:
            timeline = _ensure_datetime(merged.copy(), "timestamp")
            timeline = timeline.dropna(subset=["timestamp"]).sort_values("timestamp")
            if not timeline.empty:
                fig_time = px.line(
                    timeline,
                    x="timestamp",
                    y="anomaly_score",
                    color="company_id" if "company_id" in timeline.columns else None,
                    markers=True,
                    title="Anomaly Timeline",
                )
                fig_time.update_layout(template="plotly_dark")
                st.plotly_chart(fig_time, use_container_width=True)
            else:
                st.info("No valid timestamp values for timeline.")
        else:
            st.info("Timestamp column unavailable for timeline.")


def _render_entity_mentions_graph(entities: pd.DataFrame) -> None:
    if entities.empty or not {"news_id", "entity_name"}.issubset(entities.columns):
        st.info("Not enough entity columns to draw mention graph.")
        return

    g = nx.Graph()
    for _, row in entities.iterrows():
        news = str(row.get("news_id"))
        entity = str(row.get("entity_name"))
        if not news or not entity:
            continue
        g.add_node(news, node_type="news")
        g.add_node(entity, node_type="entity")
        g.add_edge(news, entity)

    if g.number_of_nodes() == 0:
        st.info("No nodes available for mention graph.")
        return

    pos = nx.spring_layout(g, seed=42)
    node_x_news, node_y_news, text_news = [], [], []
    node_x_ent, node_y_ent, text_ent = [], [], []
    edge_x, edge_y = [], []

    for u, v in g.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    for node, attrs in g.nodes(data=True):
        x, y = pos[node]
        if attrs.get("node_type") == "news":
            node_x_news.append(x)
            node_y_news.append(y)
            text_news.append(node)
        else:
            node_x_ent.append(x)
            node_y_ent.append(y)
            text_ent.append(node)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines", line=dict(color="#64748b", width=1), hoverinfo="none"))
    fig.add_trace(
        go.Scatter(
            x=node_x_news,
            y=node_y_news,
            mode="markers+text",
            text=text_news,
            textposition="top center",
            marker=dict(size=14, color="#38bdf8"),
            name="News",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=node_x_ent,
            y=node_y_ent,
            mode="markers+text",
            text=text_ent,
            textposition="bottom center",
            marker=dict(size=12, color="#22c55e"),
            name="Entity",
        )
    )
    fig.update_layout(title="Entity Mention Graph", template="plotly_dark", showlegend=True, height=500)
    st.plotly_chart(fig, use_container_width=True)


def _render_news_section(data: dict[str, pd.DataFrame]) -> None:
    st.header("Section 6 - Financial News Analysis")
    entities = data["entities"].copy()
    events = data["events"].copy()

    if entities.empty and events.empty:
        st.warning("entities.csv/events.csv not found or empty.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Detected Entities", int(len(entities)))
    c2.metric("Detected Events", int(len(events)))
    sentiment_count = 0
    if "sentiment" in events.columns:
        sentiment_count = int(events["sentiment"].notna().sum())
    c3.metric("Sentiment Signals", sentiment_count)

    if not events.empty and "event_type" in events.columns:
        freq = events["event_type"].value_counts().reset_index()
        freq.columns = ["event_type", "count"]
        fig_evt = px.bar(freq, x="event_type", y="count", color="count", title="Event Type Frequency")
        fig_evt.update_layout(template="plotly_dark", xaxis_title="Event Type", yaxis_title="Count")
        st.plotly_chart(fig_evt, use_container_width=True)

    with st.expander("Entity mention graph"):
        _render_entity_mentions_graph(entities)

    with st.expander("Event timeline"):
        if "event_timestamp" in events.columns:
            timeline = _ensure_datetime(events.copy(), "event_timestamp").dropna(subset=["event_timestamp"])
            if not timeline.empty:
                fig_t = px.scatter(
                    timeline,
                    x="event_timestamp",
                    y="event_type" if "event_type" in timeline.columns else None,
                    color="sentiment" if "sentiment" in timeline.columns else None,
                    size=pd.to_numeric(timeline.get("event_impact_score", 0.2), errors="coerce").fillna(0.2).abs() + 0.2,
                    hover_data=[c for c in ["news_id", "linked_entity_id", "trigger", "event_impact_score"] if c in timeline.columns],
                    title="Timeline of Financial Events",
                )
                fig_t.update_layout(template="plotly_dark")
                st.plotly_chart(fig_t, use_container_width=True)
            else:
                st.info("No valid event timestamps found.")
        else:
            st.info("event_timestamp column not present.")


def _build_llm_context(data: dict[str, pd.DataFrame]) -> str:
    context_payload = {
        "risk_predictions": data["predictions"].to_dict(orient="records")[:200],
        "network_risk": data["network"].to_dict(orient="records")[:200],
        "risk_trends": data["trends"].to_dict(orient="records")[:200],
        "events": data["events"].to_dict(orient="records")[:250],
        "entities": data["entities"].to_dict(orient="records")[:250],
    }
    return json.dumps(context_payload, indent=2, default=str)


def _run_groq_query(question: str, context: str) -> str:
    settings = get_settings()
    api_key = settings.groq_api_key.strip()
    if not api_key:
        return "Groq API key is missing. Set GROQ_API_KEY in your environment or .env to enable AI query responses."
    if ChatGroq is None:
        return "langchain_groq is not installed. Install it to enable the AI query interface."
    if ChatPromptTemplate is None:
        return "langchain is not installed. Install langchain to enable the AI query interface."

    preferred_model = settings.groq_model.strip() or "llama-3.3-70b-versatile"
    # Keep a small fallback chain so decommissioned models do not break the dashboard.
    model_candidates = [
        preferred_model,
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
    ]

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a financial risk intelligence analyst. Use ONLY the provided JSON context. "
                "If data is missing, state it explicitly. Return sections: Answer, Evidence, Reasoning, Confidence.",
            ),
            (
                "human",
                "Question:\n{question}\n\nData Context JSON:\n{context}",
            ),
        ]
    )

    last_error = ""
    for model in list(dict.fromkeys(model_candidates)):
        try:
            llm = ChatGroq(api_key=api_key, model_name=model, temperature=0.1)
            chain = prompt | llm
            result = chain.invoke({"question": question, "context": context})
            if hasattr(result, "content"):
                return str(result.content)
            return str(result)
        except Exception as exc:  # pragma: no cover - network/provider behavior
            last_error = str(exc)
            lower = last_error.lower()
            if "decommissioned" in lower or "model_decommissioned" in lower or "not found" in lower:
                continue
            return f"Groq request failed: {last_error}"

    return (
        "No available Groq model could be used. "
        f"Last error: {last_error}. "
        "Set GROQ_MODEL in .env to a currently supported model and retry."
    )


def _render_ai_query_section(data: dict[str, pd.DataFrame]) -> None:
    st.header("Section 7 - AI Query Interface")
    st.caption("Grounded Q&A over risk predictions, network analysis, trends, events, and entities.")

    default_q = "Which companies show increasing financial risk and what evidence supports that?"
    question = st.text_area("Ask a financial intelligence question", value=default_q, height=100)

    quick_col1, quick_col2, quick_col3, quick_col4 = st.columns(4)
    if quick_col1.button("Increasing risk?"):
        st.session_state["quick_q"] = "Which companies show increasing financial risk?"
    if quick_col2.button("Contagion sources?"):
        st.session_state["quick_q"] = "Which suppliers or dependencies create contagion risk?"
    if quick_col3.button("COMP-ALPHA drivers?"):
        st.session_state["quick_q"] = "What events triggered risk for COMP-ALPHA?"
    if quick_col4.button("Systemic leader?"):
        st.session_state["quick_q"] = "Which company is most systemically important and why?"

    if "quick_q" in st.session_state:
        question = st.session_state["quick_q"]

    if st.button("Run AI Analysis", type="primary"):
        context = _build_llm_context(data)
        with st.spinner("Querying Groq model with structured context..."):
            response = _run_groq_query(question, context)
        st.markdown("### AI Response")
        st.write(response)


def _headline_impact_interpretation(label: str, score: float) -> str:
    norm = label.lower()
    if "neg" in norm:
        if score > 0.9:
            return "Negative sentiment detected with very high confidence. This is a strong financial risk signal."
        return "Negative sentiment detected. Treat as potential risk pressure and monitor related entities."
    if "pos" in norm:
        if score > 0.9:
            return "Positive sentiment detected with very high confidence. Near-term sentiment risk appears reduced."
        return "Positive sentiment detected. This may provide a short-term risk cushion."
    return "Neutral sentiment detected. No direct directional risk signal from sentiment alone."


@st.cache_resource(show_spinner=False)
def _load_finbert_pipeline():
    if pipeline is None:
        return None
    return pipeline("text-classification", model="yiyanghkust/finbert-tone")


def _render_finbert_section() -> None:
    st.header("Section 8 - FinBERT News Explanation")
    st.caption("Paste a headline or short article and run FinBERT sentiment classification.")

    text = st.text_area(
        "Headline or article text",
        value="Supplier default concerns increase pressure on COMP-ALPHA cash flow outlook.",
        height=120,
    )

    if st.button("Analyze Sentiment with FinBERT"):
        nlp = _load_finbert_pipeline()
        if nlp is None:
            st.error("transformers is not installed. Install transformers to use FinBERT in this section.")
            return

        with st.spinner("Running FinBERT inference..."):
            out = nlp(text)

        if not out:
            st.warning("No output from FinBERT pipeline.")
            return

        item = out[0]
        label = str(item.get("label", "unknown"))
        score = float(item.get("score", 0.0))

        c1, c2 = st.columns(2)
        c1.metric("Sentiment", label)
        c2.metric("Confidence", f"{score:.2f}")
        st.info(_headline_impact_interpretation(label, score))


def _render_graph_insights_section(data: dict[str, pd.DataFrame], dep_graph: nx.DiGraph) -> None:
    st.header("Section 9 - Graph Insights Panel")
    pred = data["predictions"].copy()
    network = data["network"].copy()

    if pred.empty and network.empty:
        st.warning("No prediction/network data available for graph insights.")
        return

    if not pred.empty:
        score_col = "propagated_risk" if "propagated_risk" in pred.columns else "risk_score"
        pred[score_col] = pd.to_numeric(pred[score_col], errors="coerce").fillna(0.0)
        top_risky = pred.sort_values(score_col, ascending=False).head(5)
    else:
        top_risky = pd.DataFrame(columns=["company_id", "propagated_risk"])

    if dep_graph.number_of_nodes() > 0:
        degree_cent = nx.degree_centrality(dep_graph)
        connected_df = pd.DataFrame(
            [{"company_id": k, "degree_centrality": v} for k, v in degree_cent.items()]
        ).sort_values("degree_centrality", ascending=False)
    else:
        connected_df = pd.DataFrame(columns=["company_id", "degree_centrality"])

    exposure_df = pd.DataFrame()
    if not network.empty and "network_exposure_score" in network.columns:
        exposure_df = network[["company_id", "network_exposure_score"]].copy()
        exposure_df["network_exposure_score"] = pd.to_numeric(exposure_df["network_exposure_score"], errors="coerce").fillna(0.0)
        exposure_df = exposure_df.sort_values("network_exposure_score", ascending=False)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("Top Risky Companies")
        st.dataframe(top_risky[[c for c in ["company_id", score_col, "risk_level"] if c in top_risky.columns]], hide_index=True, use_container_width=True)
    with c2:
        st.subheader("Most Connected")
        st.dataframe(connected_df.head(5), hide_index=True, use_container_width=True)
    with c3:
        st.subheader("Highest Contagion Exposure")
        st.dataframe(exposure_df.head(5), hide_index=True, use_container_width=True)

    with st.expander("Bonus: Supplier Risk Cascade Visualization"):
        if dep_graph.number_of_edges() == 0:
            st.info("No directed dependency edges to render cascade.")
        else:
            nodes = list(dep_graph.nodes())
            idx = {n: i for i, n in enumerate(nodes)}
            sources, targets, values = [], [], []
            for u, v, attrs in dep_graph.edges(data=True):
                sources.append(idx[u])
                targets.append(idx[v])
                values.append(float(attrs.get("weight", 0.1)))

            sankey = go.Figure(
                go.Sankey(
                    node=dict(label=nodes, color=[_risk_color(float(dep_graph.nodes[n].get("propagated_risk", 0.0))) for n in nodes]),
                    link=dict(source=sources, target=targets, value=values),
                )
            )
            sankey.update_layout(template="plotly_dark", title="Supplier Risk Cascade (Contagion Flow)")
            st.plotly_chart(sankey, use_container_width=True)

    # Matplotlib usage for compact static overview card.
    with st.expander("Bonus: Static Centrality Snapshot"):
        if plt is None:
            st.info("matplotlib is not installed. Install matplotlib to enable static centrality snapshot.")
        elif connected_df.empty:
            st.info("No centrality scores available.")
        else:
            top = connected_df.head(5)
            fig, ax = plt.subplots(figsize=(7, 3.2))
            ax.bar(top["company_id"], top["degree_centrality"], color="#22c1aa")
            ax.set_title("Top Degree Centrality")
            ax.set_ylabel("Centrality")
            ax.set_facecolor("#0f172a")
            fig.patch.set_facecolor("#0f172a")
            ax.tick_params(axis="x", rotation=25, colors="#e2e8f0")
            ax.tick_params(axis="y", colors="#e2e8f0")
            for spine in ax.spines.values():
                spine.set_color("#334155")
            st.pyplot(fig)


def _build_report_text(data: dict[str, pd.DataFrame]) -> str:
    pred = data["predictions"]
    network = data["network"]
    trends = data["trends"]
    events = data["events"]

    line_items = [
        "Fin-IQ Risk Intelligence Report",
        "",
        f"Companies analyzed: {pred['company_id'].nunique() if 'company_id' in pred.columns else 0}",
        f"Events detected: {len(events)}",
        f"Network records: {len(network)}",
    ]

    if not pred.empty:
        score_col = "propagated_risk" if "propagated_risk" in pred.columns else "risk_score"
        p = pred.copy()
        p[score_col] = pd.to_numeric(p[score_col], errors="coerce").fillna(0.0)
        top = p.sort_values(score_col, ascending=False).head(3)
        line_items.append("")
        line_items.append("Top 3 at-risk companies:")
        for _, row in top.iterrows():
            line_items.append(f"- {row.get('company_id')}: {row.get(score_col):.3f}")

    if not trends.empty and "risk_trend" in trends.columns:
        inc = trends[trends["risk_trend"].astype(str).str.lower() == "increasing"]
        line_items.append("")
        line_items.append(f"Companies with increasing trend: {len(inc)}")

    return "\n".join(line_items)


def main() -> None:
    _load_environment()
    _apply_theme()
    data = load_data()

    st.markdown(
        f"""
        <div class="hero">
          <h1>{APP_TITLE}</h1>
          <p>{APP_SUBTITLE}</p>
          <p class="small-note">Data source: outputs directory only | Runtime: Streamlit analytics layer | Neo4j optional</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not OUTPUTS_DIR.exists():
        st.error("outputs directory not found. Run the pipeline once to generate output artifacts.")
        return

    st.sidebar.header("Navigation")
    sections = [
        "System Overview",
        "Company Risk Leaderboard",
        "Risk Trend Visualization",
        "Dependency Network Graph",
        "Transaction Anomaly Insights",
        "Financial News Analysis",
        "AI Query Interface",
        "FinBERT News Explanation",
        "Graph Insights Panel",
    ]
    selected_sections = st.sidebar.multiselect("Choose sections to display", sections, default=sections)

    if st.sidebar.button("Refresh data cache"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

    with st.sidebar.expander("Export"):
        report_text = _build_report_text(data)
        st.download_button(
            "Export dashboard summary",
            data=report_text,
            file_name="fin_iq_risk_summary.txt",
            mime="text/plain",
        )

    dep_graph = nx.DiGraph()

    if "System Overview" in selected_sections:
        _render_overview_section(data)
    if "Company Risk Leaderboard" in selected_sections:
        _render_leaderboard_section(data)
    if "Risk Trend Visualization" in selected_sections:
        _render_trends_section(data)
    if "Dependency Network Graph" in selected_sections:
        dep_graph = _render_network_section(data)
    if "Transaction Anomaly Insights" in selected_sections:
        _render_anomaly_section(data)
    if "Financial News Analysis" in selected_sections:
        _render_news_section(data)
    if "AI Query Interface" in selected_sections:
        _render_ai_query_section(data)
    if "FinBERT News Explanation" in selected_sections:
        _render_finbert_section()
    if "Graph Insights Panel" in selected_sections:
        _render_graph_insights_section(data, dep_graph)


if __name__ == "__main__":
    main()
