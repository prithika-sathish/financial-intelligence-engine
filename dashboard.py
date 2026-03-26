from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from configs.settings import get_settings

try:
    from news_analysis.finbert_analyzer import analyze_news_text
except Exception:  # pragma: no cover - optional runtime path
    analyze_news_text = None

ROOT = Path(__file__).resolve().parent
OUTPUTS_DIR = ROOT / "outputs"
SUPPLIER_CONTRACT_PATH = OUTPUTS_DIR / "supplier_decision_data.json"
RISK_PREDICTIONS_PATH = OUTPUTS_DIR / "risk_predictions.csv"
NETWORK_PATH = OUTPUTS_DIR / "network_risk_analysis.csv"
TRENDS_PATH = OUTPUTS_DIR / "risk_trends.csv"
METRICS_PATH = OUTPUTS_DIR / "metrics.json"

RISK_COLORS = {
    "Critical": "#8b1e3f",
    "High": "#d14343",
    "Medium": "#d6a822",
    "Low": "#3e9d56",
}

DEFAULT_PREDICTION_DAYS = 30
DEFAULT_SUPPLIER_LIMIT = 25
DEFAULT_IMPACT_ROWS = 8
DEFAULT_TOP_DEPENDENCY_NAMES = 6


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if "|" in stripped and not stripped.startswith("["):
            return [part.strip() for part in stripped.split("|") if part.strip()]
        try:
            parsed = ast.literal_eval(stripped)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except (ValueError, SyntaxError):
            return []
    return []


def _safe_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalize_level(level: Any) -> str | None:
    if isinstance(level, str) and level.strip():
        candidate = level.strip().capitalize()
        if candidate in RISK_COLORS:
            return candidate
    return None


def _format_metric(value: Any) -> str:
    if value is None:
        return "Data unavailable"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        text = str(value).strip()
        return text if text else "Data unavailable"


def _format_short(value: Any, decimals: int = 2) -> str:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return "Data unavailable"
    return f"{float(num):.{decimals}f}"


def _cap_risk_score(score01: Any) -> float | None:
    parsed = pd.to_numeric(score01, errors="coerce")
    if pd.isna(parsed):
        return None
    return float(min(max(float(parsed), 0.0), 0.95))


def _risk_label_from_score(score01: float | None) -> str:
    if score01 is None:
        return "Data unavailable"
    if score01 > 0.85:
        return "Critical"
    if score01 > 0.65:
        return "High"
    if score01 > 0.40:
        return "Medium"
    return "Low"


def _coerce_prediction_days(value: Any, default: int = DEFAULT_PREDICTION_DAYS) -> int:
    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return default
    days = int(round(float(parsed)))
    return days if days > 0 else default


def _classify_metric_type(metric_name: str) -> str:
    """Classify metric into semantic category for context-aware interpretation."""
    name_lower = str(metric_name or "").lower()
    
    if any(x in name_lower for x in ["cost", "expense", "amount", "spend", "budget", "impact_amount"]):
        return "financial"
    if any(x in name_lower for x in ["delay", "time", "duration", "latency"]):
        return "operational"
    if any(x in name_lower for x in ["anomaly", "unusual", "fraud", "irregularity", "outlier"]):
        return "anomaly"
    if any(x in name_lower for x in ["systemic", "importance", "centrality", "criticality"]):
        return "systemic"
    if any(x in name_lower for x in ["propagat", "cascade", "contagion", "downstream"]):
        return "propagation"
    return "general"


def _intensity_qualifier(ratio: float) -> str:
    """Return a qualitative intensity descriptor based on ratio magnitude."""
    if ratio >= 3.0:
        return "significantly"
    if ratio >= 2.0:
        return "strongly"
    if ratio >= 1.2:
        return "moderately"
    if ratio <= 0.67:
        return "notably below"
    return "near"


def _generate_context_meaning(metric_type: str, ratio: float, metric_name: str) -> str:
    """Generate category-specific, context-aware interpretation."""
    intensity = _intensity_qualifier(ratio)
    ratio_text = f"{ratio:.2f}x"
    
    if metric_type == "financial":
        if ratio >= 1.2:
            return f"suggests significant financial pressure with {ratio_text} cost exposure."
        if ratio <= 0.8:
            return f"shows cost control is within normal range at {ratio_text} baseline."
        return f"indicates cost levels near baseline ({ratio_text}), currently stable."
    
    if metric_type == "operational":
        if ratio >= 2.0:
            return f"signals strong operational delays, with {ratio_text} longer timelines."
        if ratio >= 1.2:
            return f"indicates moderate delivery lag at {ratio_text} baseline."
        return f"shows operational timelines remain stable at {ratio_text} baseline."
    
    if metric_type == "anomaly":
        if ratio >= 2.0:
            return f"reveals {intensity} irregular system behavior ({ratio_text} baseline)."
        if ratio >= 1.2:
            return f"indicates instability emerging with {ratio_text} anomaly elevation."
        return f"suggests transaction patterns remain within expected variance ({ratio_text})."
    
    if metric_type == "systemic":
        if ratio >= 2.0:
            return f"indicates this supplier is {intensity} critical in the network."
        if ratio >= 1.2:
            return f"shows notable network importance at {ratio_text} typical centrality."
        return f"reflects moderate network role at {ratio_text} baseline importance."
    
    if metric_type == "propagation":
        if ratio >= 2.0:
            return f"reveals {intensity} downstream disruption potential across {ratio_text} typical propagation."
        if ratio >= 1.2:
            return f"signals elevated cascading risk at {ratio_text} benchmark."
        return f"shows contained propagation risk within normal range ({ratio_text})."
    
    # Default for general/unknown metrics
    if ratio >= 1.2:
        return f"is {intensity} elevated at {ratio_text} baseline."
    if ratio <= 0.8:
        return f"is {intensity} baseline at {ratio_text}."
    return f"is near baseline ({ratio_text})."


def _reason_line(reason: dict[str, Any]) -> str:
    """Generate a context-aware, diverse explanation line from metric ratio."""
    metric = str(reason.get("metric_name") or "Signal").strip()
    value_raw = pd.to_numeric(reason.get("value"), errors="coerce")
    benchmark_raw = pd.to_numeric(reason.get("benchmark"), errors="coerce")
    threshold_raw = pd.to_numeric(reason.get("threshold"), errors="coerce")

    if pd.notna(value_raw) and pd.notna(benchmark_raw):
        denom = float(benchmark_raw)
        if abs(denom) > 1e-9:
            ratio = float(value_raw) / denom
            metric_type = _classify_metric_type(metric)
            meaning = _generate_context_meaning(metric_type, ratio, metric)
            return f"{metric} is {ratio:.2f}x baseline; {meaning}"

    if pd.notna(value_raw) and pd.notna(threshold_raw):
        relation = "exceeds" if float(value_raw) >= float(threshold_raw) else "remains below"
        detail = "heightening exposure" if float(value_raw) >= float(threshold_raw) else "maintaining safety margin"
        return f"{metric} {relation} threshold ({detail})."

    return f"{metric} contributed to risk, but detailed comparison unavailable."


def _impact_band(score: float | None) -> str:
    if score is None:
        return "Data unavailable"
    if score >= 0.70:
        return "HIGH"
    if score >= 0.40:
        return "MEDIUM"
    return "LOW"


def _impact_percentile_text(scores: list[float], selected: float | None) -> str:
    if selected is None:
        return "Data unavailable"
    if not scores:
        return "Data unavailable"
    rank = sum(1 for s in scores if s <= selected)
    pct = 100.0 * rank / max(1, len(scores))
    return f"~{pct:.0f}th percentile among impacted suppliers"


def _risk_sort_value(supplier: dict[str, Any]) -> float:
    return _to_float(supplier.get("risk_percentage"), _to_float(supplier.get("risk_score"), -1.0))


def _build_groq_prompt(supplier: dict[str, Any]) -> str:
    impact = supplier.get("impact") or {}
    top_impacted = impact.get("affected_suppliers") or []
    top_impacted = [row for row in top_impacted if isinstance(row, dict)][:8]

    context = {
        "supplier": supplier.get("name"),
        "risk_percentage": supplier.get("risk_percentage"),
        "risk_level": supplier.get("risk_level"),
        "recommendation": supplier.get("recommendation"),
        "impact": {
            "delay_days": impact.get("delay_days"),
            "cost_increase_percent": impact.get("cost_increase_percent"),
            "total_impact_score": impact.get("total_impact_score"),
            "top_affected": top_impacted,
        },
        "reasons": supplier.get("reasons", [])[:6],
    }
    return (
        "You are a supply chain risk analyst. Use only the provided context. "
        "Return concise output with exact sections:\n"
        "1) ALERTS (max 3 bullet points with severity: high/medium/low)\n"
        "2) RECOMMENDATIONS (max 3 action bullets)\n"
        "3) WATCHLIST METRICS (max 3 metrics to monitor over 7 days)\n"
        "If data is missing, state it explicitly and avoid guessing.\n\n"
        f"CONTEXT JSON:\n{json.dumps(context, default=str)}"
    )


def _groq_generate_ops_brief(supplier: dict[str, Any]) -> str:
    settings = get_settings()
    api_key = settings.groq_api_key.strip()
    if not api_key:
        return "GROQ_API_KEY is not configured. Set it to enable AI alerts and recommendations."

    model = settings.groq_model.strip() or "llama-3.3-70b-versatile"
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "You produce operationally useful, evidence-grounded risk briefs."},
            {"role": "user", "content": _build_groq_prompt(supplier)},
        ],
    }
    body = json.dumps(payload).encode("utf-8")

    req = urlrequest.Request(
        url="https://api.groq.com/openai/v1/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=30) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        choices = parsed.get("choices") if isinstance(parsed, dict) else None
        if not choices:
            return "No response received from Groq."
        message = choices[0].get("message", {})
        content = message.get("content") if isinstance(message, dict) else None
        return str(content).strip() if content else "No content returned by Groq."
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return f"Groq request failed: HTTP {exc.code}. {detail[:240]}"
    except Exception as exc:  # pragma: no cover - network/runtime variation
        return f"Groq request failed: {exc}"


def _is_groq_failure(text: str) -> bool:
    lowered = text.lower()
    if "groq request failed" in lowered:
        return True
    if "http 403" in lowered:
        return True
    if "error code: 1010" in lowered:
        return True
    return False


def _build_finbert_text(supplier: dict[str, Any]) -> str:
    reason_lines: list[str] = []
    for reason in supplier.get("reasons") or []:
        if isinstance(reason, dict):
            reason_lines.append(_reason_line(reason))
        elif isinstance(reason, str) and reason.strip():
            reason_lines.append(reason.strip())
    impact = supplier.get("impact") or {}
    return (
        f"Supplier {supplier.get('name')} has risk level {supplier.get('risk_level')} "
        f"with risk percentage {supplier.get('risk_percentage')}. "
        f"Estimated delay is {impact.get('delay_days')} days and cost increase is {impact.get('cost_increase_percent')} percent. "
        + " ".join(reason_lines[:5])
    )


def _derive_data_driven_decisions(supplier: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    impact = supplier.get("impact") or {}
    risk_pct = _to_float(supplier.get("risk_percentage"), 0.0)
    risk_score01 = _cap_risk_score(risk_pct / 100.0)
    risk_level = _risk_label_from_score(risk_score01)
    supplier_name = str(supplier.get("name") or "selected supplier")
    delay = _to_float(impact.get("delay_days"), 0.0)
    cost_pct = _to_float(impact.get("cost_increase_percent"), 0.0)

    impacted = [row for row in (impact.get("affected_suppliers") or []) if isinstance(row, dict)]
    impacted = sorted(impacted, key=lambda r: _to_float(r.get("impact_score"), -1.0), reverse=True)
    top_impacted = [str(r.get("name") or "") for r in impacted[:3] if str(r.get("name") or "").strip()]
    top_direct = [
        str(r.get("name") or "")
        for r in impacted
        if str(r.get("type") or "").lower() == "direct" and str(r.get("name") or "").strip()
    ][:3]

    alternatives = _parse_list(impact.get("suggested_alternatives"))

    timeseries = supplier.get("timeseries") if isinstance(supplier.get("timeseries"), dict) else {}
    risk_hist = pd.to_numeric(pd.Series(timeseries.get("risk_value", [])), errors="coerce").dropna()
    is_rising = len(risk_hist) >= 2 and float(risk_hist.iloc[-1]) > float(risk_hist.iloc[0])

    alerts: list[str] = []
    actions: list[str] = []
    watchlist: list[str] = []

    alerts.append(
        f"{risk_level.lower()}: {supplier_name} is currently assessed at {risk_pct:.1f}% risk with {len(impacted)} impacted downstream suppliers."
    )
    if delay >= 2.0:
        alerts.append(f"high: Estimated disruption delay is {delay:.1f} days, creating immediate fulfillment pressure.")
    if cost_pct >= 1.0:
        alerts.append(f"medium: Estimated cost increase is {cost_pct:.2f}%, signaling margin pressure.")
    if is_rising:
        alerts.append("medium: Risk trend is rising across the observed window and warrants tighter monitoring.")

    if alternatives:
        actions.append(
            f"Shift contingency load from {supplier_name} to {', '.join(alternatives[:3])} based on available alternatives ranking."
        )
    if top_direct:
        actions.append(
            f"Increase buffer stock for components tied to direct dependencies: {', '.join(top_direct)}."
        )
    if top_impacted:
        actions.append(
            f"Prioritize mitigation reviews for top impacted suppliers: {', '.join(top_impacted)}."
        )
    if is_rising:
        actions.append("Escalate to daily monitoring until trend stabilizes over consecutive windows.")

    watchlist.append(f"risk: {risk_pct:.1f}% ({risk_level})")
    watchlist.append(f"delay_days: {delay:.2f}")
    watchlist.append(f"cost_increase_pct: {cost_pct:.2f}")
    return alerts[:3], actions[:3], watchlist[:3]


def _local_recommended_actions(supplier: dict[str, Any], fallback_note: str | None = None) -> str:
    alerts, actions, watchlist = _derive_data_driven_decisions(supplier)
    risk_pct = _to_float(supplier.get("risk_percentage"), 0.0)

    sentiment = "neutral"
    confidence = 0.0
    if analyze_news_text is not None:
        try:
            sentiment_payload = analyze_news_text(_build_finbert_text(supplier))
            sentiment = str(sentiment_payload.get("sentiment") or "neutral")
            confidence = _to_float(sentiment_payload.get("sentiment_confidence"), 0.0)
        except Exception:
            sentiment = "neutral"
            confidence = 0.0

    if sentiment == "negative" and confidence >= 0.5:
        alerts.append("medium: FinBERT sentiment is negative; monitor external risk news closely.")

    if risk_pct >= 85:
        actions.insert(0, "Trigger contingency workflow and assign named owners for top mitigation actions.")

    result_lines = [
        "### ALERTS",
        *[f"- {item}" for item in alerts[:3]],
        "",
        "### RECOMMENDED ACTIONS",
        *[f"- {item}" for item in actions[:3]],
        "",
        "### WATCHLIST METRICS (7 DAYS)",
        *[f"- {item}" for item in watchlist[:3]],
        "",
        f"Sentiment source: FinBERT ({sentiment}, confidence {confidence:.2f})",
    ]
    if fallback_note:
        result_lines.append(f"Fallback note: {fallback_note}")
    return "\n".join(result_lines)


def _resolve_recommended_actions(supplier: dict[str, Any]) -> str:
    local_brief = _local_recommended_actions(supplier)
    groq_result = _groq_generate_ops_brief(supplier)
    if _is_groq_failure(groq_result):
        return _local_recommended_actions(supplier, fallback_note=groq_result)
    # Keep deterministic data-driven recommendations primary and append optional AI note.
    return f"{local_brief}\n\n### AI NOTE\n{groq_result}"


def _compute_quant_reasons(row: pd.Series, risk_df: pd.DataFrame) -> list[dict[str, Any]]:
    skip_cols = {
        "company_id",
        "name",
        "risk_level",
        "systemic_risk_level",
        "recommended_action",
        "potential_impact_nodes",
        "suggested_alternatives",
        "dependency_chain",
    }
    numeric_cols = [
        col
        for col in risk_df.columns
        if col not in skip_cols and pd.api.types.is_numeric_dtype(risk_df[col])
    ]

    reasons: list[dict[str, Any]] = []
    for col in numeric_cols:
        value = pd.to_numeric(row.get(col), errors="coerce")
        if pd.isna(value):
            continue
        series = pd.to_numeric(risk_df[col], errors="coerce").dropna()
        if series.empty:
            continue
        benchmark = float(series.mean())
        threshold = float(series.quantile(0.75))
        reasons.append(
            {
                "metric_name": col,
                "value": float(value),
                "benchmark": benchmark,
                "threshold": threshold,
                "description": None,
            }
        )

    reasons.sort(
        key=lambda r: abs(float(r.get("value", 0.0)) - float(r.get("benchmark", 0.0))),
        reverse=True,
    )
    return reasons[:5]


def _parse_reason_objects(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, str):
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list):
                return [r for r in parsed if isinstance(r, dict)]
        except (ValueError, SyntaxError):
            return []
    return []


def _parse_affected_suppliers(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, list):
                    return [item for item in parsed if isinstance(item, dict)]
            except (ValueError, SyntaxError):
                return []
    return []


def _build_graph_from_outputs(risk_df: pd.DataFrame, network_df: pd.DataFrame) -> dict[str, Any]:
    nodes = []
    if not risk_df.empty and "company_id" in risk_df.columns:
        for _, row in risk_df.iterrows():
            node_name = str(row.get("company_id") or "").strip()
            if not node_name:
                continue
            nodes.append({"id": node_name, "name": node_name})

    edges: list[dict[str, str]] = []
    if not network_df.empty and "dependency_chain" in network_df.columns:
        for _, row in network_df.iterrows():
            chain = str(row.get("dependency_chain") or "").strip()
            if "->" not in chain:
                continue
            parts = [p.strip() for p in chain.split("->") if p.strip()]
            for src, dst in zip(parts[:-1], parts[1:]):
                edges.append({"source": src, "target": dst})

    unique_edges = {
        (edge["source"], edge["target"]): edge for edge in edges if edge.get("source") and edge.get("target")
    }

    return {
        "nodes": nodes,
        "edges": list(unique_edges.values()),
    }


def _normalize_supplier(
    row: pd.Series,
    risk_df: pd.DataFrame,
    global_graph: dict[str, Any],
) -> dict[str, Any]:
    name = str(row.get("name") or row.get("company_id") or "").strip()
    score = row.get("risk_score", row.get("propagated_risk"))
    risk_score = _to_float(score, default=float("nan"))
    risk_percentage = row.get("risk_percentage")
    if risk_percentage is None and not pd.isna(risk_score):
        risk_percentage = float(risk_score) * 100.0
    capped_score = _cap_risk_score(_to_float(risk_percentage, 0.0) / 100.0 if risk_percentage is not None else risk_score)
    if capped_score is not None:
        risk_percentage = capped_score * 100.0

    level = _normalize_level(row.get("risk_level") or row.get("systemic_risk_level"))
    if capped_score is not None:
        level = _risk_label_from_score(capped_score)

    reason_objects = _parse_reason_objects(row.get("reasons"))
    if not reason_objects:
        reason_objects = _compute_quant_reasons(row, risk_df)

    impacted = _parse_affected_suppliers(row.get("affected_suppliers"))
    if not impacted:
        affected_list = _parse_list(row.get("potential_impact_nodes"))
        impacted = [{"name": item, "type": "unknown", "impact_score": None, "reasons": []} for item in affected_list]

    cost_pct = row.get("cost_increase_percent")
    if cost_pct is None and "estimated_cost_impact" in row.index:
        est = pd.to_numeric(row.get("estimated_cost_impact"), errors="coerce")
        if pd.notna(est):
            cost_pct = float(est) * 100.0

    delay_days = row.get("delay_days")
    total_impact_score = row.get("total_impact_score")
    if total_impact_score is None and impacted:
        scored = [
            _to_float(item.get("impact_score"), 0.0)
            for item in impacted
            if isinstance(item, dict) and item.get("impact_score") is not None
        ]
        if scored:
            total_impact_score = float(sum(scored))
    suggested_alternatives = _parse_list(row.get("suggested_alternatives"))

    recs = row.get("recommendation")
    if isinstance(recs, str):
        rec_list = _parse_list(recs)
    elif isinstance(recs, list):
        rec_list = [str(x) for x in recs if str(x).strip()]
    else:
        action = str(row.get("recommended_action") or "").strip()
        rec_list = [action] if action else []

    validation = row.get("validation") if isinstance(row.get("validation"), dict) else {}
    timeseries = row.get("timeseries") if isinstance(row.get("timeseries"), dict) else {}

    return {
        "name": name if name else "Data unavailable",
        "risk_score": None if pd.isna(risk_score) else float(risk_score),
        "risk_percentage": risk_percentage,
        "prediction_days": _coerce_prediction_days(row.get("prediction_days")),
        "risk_level": level,
        "reasons": reason_objects,
        "impact": {
            "affected_suppliers": impacted,
            "total_impact_score": total_impact_score,
            "delay_days": delay_days,
            "cost_increase_percent": cost_pct,
            "suggested_alternatives": suggested_alternatives,
        },
        "recommendation": rec_list,
        "validation": validation,
        "timeseries": timeseries,
        "graph": global_graph,
    }


def _normalize_contract_supplier(item: dict[str, Any], global_graph: dict[str, Any]) -> dict[str, Any]:
    supplier = dict(item)
    supplier.setdefault("name", "Data unavailable")
    raw_pct = supplier.get("risk_percentage")
    if raw_pct is None and supplier.get("risk_score") is not None:
        raw_pct = _to_float(supplier.get("risk_score"), 0.0) * 100.0
    capped_score = _cap_risk_score(_to_float(raw_pct, 0.0) / 100.0 if raw_pct is not None else None)
    if capped_score is not None:
        supplier["risk_percentage"] = capped_score * 100.0
    supplier["risk_level"] = _risk_label_from_score(capped_score) if capped_score is not None else _normalize_level(supplier.get("risk_level"))
    supplier["prediction_days"] = _coerce_prediction_days(supplier.get("prediction_days"))
    supplier.setdefault("reasons", [])
    supplier.setdefault("impact", {})
    if isinstance(supplier.get("impact"), dict):
        supplier["impact"]["suggested_alternatives"] = _parse_list(supplier["impact"].get("suggested_alternatives"))
    supplier.setdefault("recommendation", [])
    supplier.setdefault("validation", {})
    supplier.setdefault("timeseries", {})
    supplier.setdefault("graph", global_graph)
    return supplier


@st.cache_data(show_spinner=False)
def load_bundle() -> dict[str, Any]:
    risk_df = pd.read_csv(RISK_PREDICTIONS_PATH) if RISK_PREDICTIONS_PATH.exists() else pd.DataFrame()
    network_df = pd.read_csv(NETWORK_PATH) if NETWORK_PATH.exists() else pd.DataFrame()
    trends_df = pd.read_csv(TRENDS_PATH) if TRENDS_PATH.exists() else pd.DataFrame()
    metrics = _safe_json(METRICS_PATH)

    global_graph = _build_graph_from_outputs(risk_df, network_df)

    contract_payload = _safe_json(SUPPLIER_CONTRACT_PATH)
    suppliers: list[dict[str, Any]] = []

    if isinstance(contract_payload, dict) and isinstance(contract_payload.get("suppliers"), list):
        suppliers = [_normalize_contract_supplier(item, global_graph) for item in contract_payload["suppliers"] if isinstance(item, dict)]
    elif isinstance(contract_payload, list):
        suppliers = [_normalize_contract_supplier(item, global_graph) for item in contract_payload if isinstance(item, dict)]
    elif not risk_df.empty:
        suppliers = [_normalize_supplier(row, risk_df, global_graph) for _, row in risk_df.iterrows()]

    supplier_by_name = {
        str(s.get("name")): s for s in suppliers if str(s.get("name")).strip() and str(s.get("name")) != "Data unavailable"
    }

    if not trends_df.empty and "company_id" in trends_df.columns:
        for _, row in trends_df.iterrows():
            name = str(row.get("company_id") or "").strip()
            if not name or name not in supplier_by_name:
                continue
            history = _parse_list(row.get("risk_history"))
            risk_values: list[float] = []
            for item in history:
                try:
                    risk_values.append(float(item))
                except (TypeError, ValueError):
                    continue
            if risk_values:
                supplier_by_name[name]["timeseries"].setdefault(
                    "dates", [f"Observation {idx + 1}" for idx in range(len(risk_values))]
                )
                supplier_by_name[name]["timeseries"].setdefault("risk_values", risk_values)

    return {
        "suppliers": suppliers,
        "risk_df": risk_df,
        "network_df": network_df,
        "trends_df": trends_df,
        "metrics": metrics,
        "global_graph": global_graph,
    }


def _risk_chip(level: str) -> str:
    color = RISK_COLORS.get(level or "", "#98a2b3")
    label = level if level else "Data unavailable"
    return (
        f"<span style='display:inline-block;padding:2px 10px;border-radius:999px;"
        f"font-size:12px;font-weight:600;background:{color}22;color:{color};border:1px solid {color}66;'>"
        f"{label}</span>"
    )


def _apply_styles() -> None:
    st.set_page_config(page_title="Supply Chain Decision Console", layout="wide")
    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&display=swap');

            :root {
                --bg-page: linear-gradient(180deg, #f6f7f9 0%, #f2f4f7 100%);
                --bg-card: #ffffff;
                --border-card: #e4e7ec;
                --text-primary: #101828;
                --text-secondary: #344054;
                --text-muted: #667085;
            }

            [data-theme="dark"] {
                --bg-page: linear-gradient(180deg, #0f172a 0%, #111827 100%);
                --bg-card: #101827;
                --border-card: #1f2937;
                --text-primary: #f3f4f6;
                --text-secondary: #d1d5db;
                --text-muted: #9ca3af;
            }

            .stApp {
                background: var(--bg-page);
            }

            html, body, [class*="css"] {
                font-family: 'Manrope', sans-serif;
            }

            .title-wrap {
                max-width: 1200px;
                margin: 0 auto 14px auto;
                padding: 4px 8px;
            }

            .title-wrap h1 {
                margin-bottom: 4px;
                font-size: 30px;
                font-weight: 800;
                color: var(--text-primary);
            }

            .title-wrap p {
                margin: 0;
                color: var(--text-muted);
                font-size: 14px;
            }

            .card {
                background: var(--bg-card);
                border: 1px solid var(--border-card);
                border-radius: 14px;
                padding: 16px 18px;
                margin-bottom: 12px;
            }

            /* Keep text readable inside cards in both light/dark themes */
            .card, .card p, .card li, .card span, .card div, .card label {
                color: var(--text-secondary) !important;
            }

            .card h1, .card h2, .card h3, .card h4, .card h5 {
                color: var(--text-primary) !important;
            }

            .section-title {
                font-size: 15px;
                font-weight: 700;
                color: var(--text-secondary);
                margin-bottom: 8px;
                text-transform: uppercase;
                letter-spacing: 0.04em;
            }

            .prediction {
                font-size: 34px;
                font-weight: 800;
                line-height: 1.24;
                color: var(--text-primary);
            }

            .supplier-list-title {
                font-size: 14px;
                font-weight: 700;
                color: var(--text-secondary);
                margin-bottom: 10px;
                text-transform: uppercase;
                letter-spacing: 0.04em;
            }

            .muted-note {
                color: var(--text-muted);
                font-size: 13px;
            }

            ul.clean {
                margin: 0;
                padding-left: 18px;
            }

            ul.clean li {
                margin-bottom: 8px;
                color: var(--text-secondary);
                font-size: 14px;
                line-height: 1.4;
            }

            .plain-link a {
                color: var(--text-secondary);
                text-decoration: none;
                font-weight: 700;
            }

            [data-testid="stMarkdownContainer"] p,
            [data-testid="stMarkdownContainer"] li,
            [data-testid="stMarkdownContainer"] span {
                color: var(--text-secondary);
            }

            [data-testid="stMarkdownContainer"] h1,
            [data-testid="stMarkdownContainer"] h2,
            [data-testid="stMarkdownContainer"] h3,
            [data-testid="stMarkdownContainer"] h4,
            [data-testid="stMarkdownContainer"] h5,
            [data-testid="stMarkdownContainer"] h6,
            [data-testid="stMarkdownContainer"] strong {
                color: var(--text-primary) !important;
            }

            [data-testid="stButton"] button {
                background: #0f172a;
                color: #f8fafc !important;
                border: 1px solid #1f2937;
            }

            [data-testid="stButton"] button:hover {
                background: #111827;
                border-color: #334155;
            }

            [data-testid="stButton"] button p,
            [data-testid="stButton"] button span,
            [data-testid="stButton"] button div {
                color: #f8fafc !important;
            }

            [data-testid="stSidebar"] {
                border-right: 1px solid var(--border-card);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _initialize_selection(suppliers: list[dict[str, Any]]) -> None:
    if "selected_supplier" not in st.session_state:
        st.session_state.selected_supplier = suppliers[0]["name"] if suppliers else None
    if "page" not in st.session_state:
        st.session_state.page = "Main Dashboard"
    if "risk_filter" not in st.session_state:
        st.session_state.risk_filter = "All"
    if "supplier_query" not in st.session_state:
        st.session_state.supplier_query = ""
    if "supplier_limit" not in st.session_state:
        st.session_state.supplier_limit = DEFAULT_SUPPLIER_LIMIT
    if "impact_row_limit" not in st.session_state:
        st.session_state.impact_row_limit = DEFAULT_IMPACT_ROWS


def _find_selected_supplier(suppliers: list[dict[str, Any]]) -> dict[str, Any] | None:
    selected_name = st.session_state.get("selected_supplier")
    for supplier in suppliers:
        if supplier.get("name") == selected_name:
            return supplier
    return suppliers[0] if suppliers else None


def _render_supplier_list(suppliers: list[dict[str, Any]]) -> None:
    st.markdown("<div class='supplier-list-title'>Suppliers</div>", unsafe_allow_html=True)
    for supplier in suppliers:
        supplier_name = str(supplier.get("name", "Data unavailable"))
        risk_level = supplier.get("risk_level")

        is_selected = st.session_state.get("selected_supplier") == supplier_name
        label = f"{supplier_name}"
        if is_selected:
            label = f"{supplier_name}  (selected)"

        left, right = st.columns([0.72, 0.28], gap="small")
        with left:
            if st.button(label, key=f"supplier_{supplier_name}", width="stretch"):
                st.session_state.selected_supplier = supplier_name
        with right:
            st.markdown(_risk_chip(risk_level), unsafe_allow_html=True)


def _filter_suppliers(suppliers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    risk_filter = st.session_state.get("risk_filter", "All")
    query = str(st.session_state.get("supplier_query", "")).strip().lower()
    limit = int(st.session_state.get("supplier_limit", DEFAULT_SUPPLIER_LIMIT))

    filtered = suppliers
    if risk_filter != "All":
        filtered = [s for s in filtered if str(s.get("risk_level") or "") == risk_filter]
    if query:
        filtered = [s for s in filtered if query in str(s.get("name") or "").lower()]

    return filtered[: max(1, limit)]


def _render_prediction(supplier: dict[str, Any]) -> None:
    name = str(supplier.get("name") or "Data unavailable")
    risk_pct = supplier.get("risk_percentage")
    if risk_pct is None and supplier.get("risk_score") is not None:
        risk_pct = float(supplier.get("risk_score")) * 100.0
    score01 = _cap_risk_score(_to_float(risk_pct, 0.0) / 100.0 if risk_pct is not None else None)
    risk_text = "Data unavailable" if score01 is None else f"{score01 * 100.0:.0f}%"
    risk_label = _risk_label_from_score(score01)
    risk_phrase = "Data unavailable" if score01 is None else f"{risk_text} ({risk_label})"

    st.markdown("<div class='section-title'>Prediction</div>", unsafe_allow_html=True)
    st.markdown(
        (
            "<div class='prediction'>"
            f"Supplier {name} Risk: {risk_phrase}."
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_bullets(title: str, items: list[str]) -> None:
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown(f"<div class='section-title'>{title}</div>", unsafe_allow_html=True)
    if items:
        bullet_lines = "".join(f"<li>{item}</li>" for item in items)
        st.markdown(f"<ul class='clean'>{bullet_lines}</ul>", unsafe_allow_html=True)
    else:
        st.markdown("<p class='muted-note'>Data unavailable</p>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _build_relation_map(graph: dict[str, Any], supplier_name: str) -> tuple[set[str], set[str]]:
    graph_nx = nx.DiGraph()
    for node in graph.get("nodes", []):
        node_id = str(node.get("id") or node.get("name") or "").strip()
        if node_id:
            graph_nx.add_node(node_id)
    for edge in graph.get("edges", []):
        src = str(edge.get("source") or "").strip()
        dst = str(edge.get("target") or "").strip()
        if src and dst:
            graph_nx.add_edge(src, dst)

    if supplier_name not in graph_nx:
        return set(), set()

    direct = set(graph_nx.successors(supplier_name))
    indirect = set()
    for node in direct:
        indirect.update(nx.descendants(graph_nx, node))
    indirect.discard(supplier_name)
    indirect = {n for n in indirect if n not in direct}
    return direct, indirect


def _humanize_impact_reasons(reasons: list[Any], dependency_type: str) -> str:
    text_reasons = [str(r).strip() for r in reasons if str(r).strip()]
    dep_weight = None
    sub = None
    for line in text_reasons:
        lower = line.lower()
        if lower.startswith("dependency weight"):
            dep_weight = pd.to_numeric(line.split(":", 1)[-1].strip(), errors="coerce")
        if lower.startswith("substitutability"):
            sub = pd.to_numeric(line.split(":", 1)[-1].strip(), errors="coerce")

    summary: list[str] = []
    if pd.notna(dep_weight) and pd.notna(sub):
        if float(sub) <= 0.35:
            summary.append(f"High dependency ({float(dep_weight):.2f}) with limited alternatives increases disruption risk.")
        else:
            summary.append(f"Dependency remains material ({float(dep_weight):.2f}), but alternatives reduce part of the impact.")
    if dependency_type.lower() == "direct":
        summary.append("Direct dependency amplifies immediate operational impact.")
    elif dependency_type.lower() == "indirect":
        summary.append("Indirect dependency transmits risk through upstream links.")

    plain = [line for line in text_reasons if ":" not in line][:1]
    summary.extend(plain)
    return " ".join(summary) if summary else "Impact is driven by dependency structure and available alternatives."


def _render_impact(supplier: dict[str, Any], graph: dict[str, Any]) -> None:
    impact = supplier.get("impact", {}) or {}
    affected_suppliers = impact.get("affected_suppliers") or []
    ranked_rows = [item for item in affected_suppliers if isinstance(item, dict)]

    if not ranked_rows:
        fallback_names = _parse_list(impact.get("affected_nodes"))
        ranked_rows = [
            {"name": name, "impact_score": None, "type": "unknown", "reasons": []}
            for name in fallback_names
        ]

    def _score_key(item: dict[str, Any]) -> float:
        score = item.get("impact_score")
        if score is None:
            return -1.0
        return _to_float(score, -1.0)

    ranked_rows = sorted(ranked_rows, key=_score_key, reverse=True)

    numeric_scores = [
        _to_float(item.get("impact_score"), 0.0)
        for item in ranked_rows
        if item.get("impact_score") is not None
    ]

    direct_names = [str(item.get("name")) for item in ranked_rows if str(item.get("type")).lower() == "direct"]
    indirect_names = [str(item.get("name")) for item in ranked_rows if str(item.get("type")).lower() == "indirect"]

    if not direct_names and not indirect_names:
        affected_names = [str(item.get("name")) for item in ranked_rows if str(item.get("name") or "").strip()]
        direct_set, indirect_set = _build_relation_map(graph, str(supplier.get("name") or ""))
        direct_names = [name for name in affected_names if name in direct_set]
        indirect_names = [name for name in affected_names if name in indirect_set]

    delay = impact.get("delay_days")
    cost_pct = impact.get("cost_increase_percent")
    total_impact = impact.get("total_impact_score")
    if total_impact is None and numeric_scores:
        total_impact = float(sum(numeric_scores))

    selected_impact_score = _to_float(total_impact, default=float("nan"))
    selected_impact = None if pd.isna(selected_impact_score) else float(selected_impact_score)
    impact_band = _impact_band(selected_impact)
    pct_text = _impact_percentile_text(numeric_scores, selected_impact)

    top_names = [str(item.get("name") or "") for item in ranked_rows if str(item.get("name") or "").strip()]
    top_names = top_names[:DEFAULT_TOP_DEPENDENCY_NAMES]
    direct_summary = f"{len(direct_names)}"
    indirect_summary = f"{len(indirect_names)}"

    items = [
        f"Total impact score: {_format_short(total_impact, 3)}",
        f"Impact severity: {impact_band} ({pct_text})",
        f"Number of affected suppliers: {len(ranked_rows)}",
        f"Top impacted suppliers: {', '.join(top_names) if top_names else 'Data unavailable'}",
        f"Direct dependencies (count): {direct_summary}",
        f"Indirect dependencies (count): {indirect_summary}",
        f"Estimated delay (days): {_format_short(delay, 2)}",
        f"Estimated cost increase (%): {_format_short(cost_pct, 2)}",
    ]
    _render_bullets("Impact", items)

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Affected Suppliers (Ranked)</div>", unsafe_allow_html=True)
    if ranked_rows:
        limit = int(st.session_state.get("impact_row_limit", DEFAULT_IMPACT_ROWS))
        limit = min(8, max(5, limit))
        limited_rows = ranked_rows[:limit]
        display_rows: list[dict[str, Any]] = []
        for item in limited_rows:
            reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
            display_rows.append(
                {
                    "supplier": item.get("name") or "Data unavailable",
                    "impact_score": _format_short(item.get("impact_score"), 3),
                    "dependency_type": item.get("type") or "Data unavailable",
                    "explanation": _humanize_impact_reasons(reasons, str(item.get("type") or "unknown")),
                }
            )
        st.dataframe(pd.DataFrame(display_rows), width="stretch", hide_index=True)
        if len(ranked_rows) > len(limited_rows):
            remaining = len(ranked_rows) - len(limited_rows)
            st.caption(f"+{remaining} additional low-impact suppliers")
    else:
        st.write("Data unavailable")
    st.markdown("</div>", unsafe_allow_html=True)


def _render_why(supplier: dict[str, Any]) -> None:
    reasons = supplier.get("reasons") or []
    reason_lines: list[str] = []
    for reason in reasons:
        if isinstance(reason, dict):
            reason_lines.append(_reason_line(reason))
        elif isinstance(reason, str) and reason.strip():
            reason_lines.append(reason.strip())
    _render_bullets("Why", reason_lines[:5])


def _render_priority_alerts(supplier: dict[str, Any]) -> None:
    alerts, _, _ = _derive_data_driven_decisions(supplier)
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Priority Alerts</div>", unsafe_allow_html=True)
    if alerts:
        for line in alerts:
            st.error(line)
    else:
        st.write("No active priority alerts for the selected supplier.")
    st.markdown("</div>", unsafe_allow_html=True)


def _render_recommendations(supplier: dict[str, Any]) -> None:
    _, derived_actions, _ = _derive_data_driven_decisions(supplier)
    recs = [str(item).strip() for item in (supplier.get("recommendation") or []) if str(item).strip()]
    combined = derived_actions + [r for r in recs if r not in derived_actions]
    _render_bullets("Recommendation", combined[:5])


def _render_ops_ai_panel(supplier: dict[str, Any]) -> None:
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Recommended Actions</div>", unsafe_allow_html=True)

    supplier_name = str(supplier.get("name") or "unknown")
    cache_key = f"ops_actions::{supplier_name}"
    source_key = f"ops_actions_source::{supplier_name}"

    if cache_key not in st.session_state:
        with st.spinner("Generating recommended actions..."):
            resolved = _resolve_recommended_actions(supplier)
        st.session_state[cache_key] = resolved
        st.session_state[source_key] = "Groq/FinBERT fallback"

    c1, c2 = st.columns([1, 1])
    if c1.button("Refresh Recommended Actions", key=f"ops_refresh_{supplier_name}", width="stretch"):
        with st.spinner("Refreshing recommended actions..."):
            st.session_state[cache_key] = _resolve_recommended_actions(supplier)
            st.session_state[source_key] = "Groq/FinBERT fallback"
    if c2.button("Reset Recommendation Cache", key=f"ops_reset_{supplier_name}", width="stretch"):
        st.session_state.pop(cache_key, None)
        st.session_state.pop(source_key, None)
        st.rerun()

    brief = st.session_state.get(cache_key)
    if brief:
        st.caption(f"Source: {st.session_state.get(source_key, 'Groq/FinBERT fallback')}")
        st.markdown(str(brief))
    else:
        st.write("Recommended actions unavailable.")
    st.markdown("</div>", unsafe_allow_html=True)


def _render_drilldown_links() -> None:
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Drill-Down</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    if c1.button("View Proof & Validation", width="stretch"):
        st.session_state.page = "Proof & Validation"
        st.rerun()
    if c2.button("View Dependency Network", width="stretch"):
        st.session_state.page = "Dependency Network"
        st.rerun()
    if c3.button("View Temporal Analysis", width="stretch"):
        st.session_state.page = "Temporal Analysis"
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def _render_signal_validation(supplier: dict[str, Any]) -> None:
    rows = []
    for reason in supplier.get("reasons") or []:
        if not isinstance(reason, dict):
            continue
        value = reason.get("value")
        benchmark = reason.get("benchmark")
        deviation = None
        if value is not None and benchmark is not None:
            try:
                deviation = float(value) - float(benchmark)
            except (TypeError, ValueError):
                deviation = None
        rows.append(
            {
                "metric": reason.get("metric_name") or "Data unavailable",
                "value": _format_metric(value),
                "benchmark": _format_metric(benchmark),
                "threshold": _format_metric(reason.get("threshold")),
                "deviation": _format_metric(deviation),
            }
        )

    if not rows:
        return

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Signal Validation</div>", unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_model_validation(supplier: dict[str, Any]) -> None:
    validation = supplier.get("validation") or {}
    accuracy = validation.get("accuracy")
    precision = validation.get("precision")
    recall = validation.get("recall")

    backtest = validation.get("backtest") if isinstance(validation.get("backtest"), dict) else {}
    total_cases = backtest.get("total_cases")
    correct = backtest.get("correct_predictions")
    fp = backtest.get("false_positives")
    fn = backtest.get("false_negatives")

    if accuracy is None:
        total_num = pd.to_numeric(total_cases, errors="coerce")
        correct_num = pd.to_numeric(correct, errors="coerce")
        if pd.notna(total_num) and pd.notna(correct_num) and float(total_num) > 0:
            accuracy = float(correct_num) / float(total_num)

    has_perf = not (accuracy is None and precision is None and recall is None)
    has_backtest = not (total_cases is None and correct is None and fp is None and fn is None)

    if not has_perf and not has_backtest:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>Proof & Validation</div>", unsafe_allow_html=True)
        st.write("Validation metrics are not present in current output artifacts.")
        st.caption("Add validation fields in supplier_decision_data.json to enable Model Performance and Backtesting sections.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if has_perf:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>Model Performance</div>", unsafe_allow_html=True)
        st.write(f"Accuracy: {_format_metric(accuracy)}")
        st.write(f"Precision: {_format_metric(precision)}")
        st.write(f"Recall: {_format_metric(recall)}")
        st.markdown("</div>", unsafe_allow_html=True)

    if has_backtest:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>Backtesting</div>", unsafe_allow_html=True)
        st.write(f"Total cases: {total_cases if total_cases is not None else 'Data unavailable'}")
        st.write(f"Correct predictions: {correct if correct is not None else 'Data unavailable'}")
        st.write(f"False positives: {fp if fp is not None else 'Data unavailable'}")
        st.write(f"False negatives: {fn if fn is not None else 'Data unavailable'}")
        st.markdown("</div>", unsafe_allow_html=True)


def _render_network_page(supplier: dict[str, Any], graph: dict[str, Any]) -> None:
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Dependency Network</div>", unsafe_allow_html=True)

    graph_nx = nx.DiGraph()
    for node in graph.get("nodes", []):
        node_id = str(node.get("id") or node.get("name") or "").strip()
        if node_id:
            graph_nx.add_node(node_id)
    for edge in graph.get("edges", []):
        src = str(edge.get("source") or "").strip()
        dst = str(edge.get("target") or "").strip()
        if src and dst:
            graph_nx.add_edge(src, dst)

    if graph_nx.number_of_nodes() == 0:
        st.write("Data unavailable")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    supplier_name = str(supplier.get("name") or "")
    direct_set, indirect_set = _build_relation_map(graph, supplier_name)

    pos = nx.spring_layout(graph_nx, seed=42)
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    for src, dst in graph_nx.edges():
        x0, y0 = pos[src]
        x1, y1 = pos[dst]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    node_x: list[float] = []
    node_y: list[float] = []
    node_label: list[str] = []
    node_role: list[str] = []
    node_color: list[str] = []

    for node in graph_nx.nodes():
        node_x.append(pos[node][0])
        node_y.append(pos[node][1])
        node_label.append(node)
        if node == supplier_name:
            role = "selected"
            color = "#111827"
        elif node in direct_set:
            role = "direct"
            color = "#d14343"
        elif node in indirect_set:
            role = "indirect"
            color = "#d6a822"
        else:
            role = "other"
            color = "#98a2b3"
        node_role.append(role)
        node_color.append(color)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line=dict(color="#d0d5dd", width=1),
            hoverinfo="none",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers+text",
            text=node_label,
            textposition="top center",
            marker=dict(size=12, color=node_color),
            customdata=node_role,
            hovertemplate="Supplier: %{text}<br>Role: %{customdata}<extra></extra>",
        )
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=10),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        height=520,
    )
    event = st.plotly_chart(fig, width="stretch", on_select="rerun", key="network_graph")
    if event and event.get("selection") and event["selection"].get("points"):
        point_index = event["selection"]["points"][0].get("point_index")
        if point_index is not None and 0 <= point_index < len(node_label):
            st.session_state.selected_supplier = node_label[point_index]
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Affected Suppliers</div>", unsafe_allow_html=True)
    affected_rows = [{"name": name, "type": "direct"} for name in sorted(direct_set)] + [
        {"name": name, "type": "indirect"} for name in sorted(indirect_set)
    ]
    if affected_rows:
        st.dataframe(pd.DataFrame(affected_rows), hide_index=True, width="stretch")
    else:
        st.write("Data unavailable")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Impact Analysis</div>", unsafe_allow_html=True)
    if st.button("Simulate supplier removal", width="stretch"):
        trimmed = graph_nx.copy()
        if supplier_name in trimmed:
            trimmed.remove_node(supplier_name)
        remaining_affected = sorted(direct_set.intersection(set(trimmed.nodes())) | indirect_set.intersection(set(trimmed.nodes())))
        st.write(f"Affected suppliers after removing {supplier_name}: {len(remaining_affected)}")
        if remaining_affected:
            st.write(", ".join(remaining_affected))
        else:
            st.write("Data unavailable")
    st.markdown("</div>", unsafe_allow_html=True)


def _build_temporal_frame(supplier: dict[str, Any]) -> pd.DataFrame:
    timeseries = supplier.get("timeseries") or {}
    dates = timeseries.get("dates") if isinstance(timeseries.get("dates"), list) else []
    risk_values = timeseries.get("risk_values") if isinstance(timeseries.get("risk_values"), list) else []
    delay_values = timeseries.get("delay_values") if isinstance(timeseries.get("delay_values"), list) else []
    anomaly_flags = timeseries.get("anomaly_flags") if isinstance(timeseries.get("anomaly_flags"), list) else []

    length = max(len(dates), len(risk_values), len(delay_values), len(anomaly_flags))
    if length == 0:
        return pd.DataFrame()

    if not dates:
        dates = [f"Observation {idx + 1}" for idx in range(length)]

    def _pad(values: list[Any]) -> list[Any]:
        return values + [None] * (length - len(values))

    return pd.DataFrame(
        {
            "time": _pad(dates),
            "risk_value": _pad(risk_values),
            "delay_value": _pad(delay_values),
            "anomaly_flag": _pad(anomaly_flags),
        }
    )


def _derive_temporal_proxies(frame: pd.DataFrame, supplier: dict[str, Any]) -> tuple[pd.DataFrame, bool, bool]:
    """Backfill delay/anomaly trends from risk history when explicit series are missing.

    Returns: (updated_frame, used_delay_proxy, used_anomaly_proxy)
    """
    if frame.empty:
        return frame, False, False

    out = frame.copy()
    used_delay_proxy = False
    used_anomaly_proxy = False

    risk_series = pd.to_numeric(out["risk_value"], errors="coerce")
    delay_series = pd.to_numeric(out["delay_value"], errors="coerce")
    anomaly_series = pd.to_numeric(out["anomaly_flag"], errors="coerce")

    # Delay proxy: scale current estimated delay across normalized risk history.
    if delay_series.notna().sum() == 0 and risk_series.notna().sum() >= 2:
        impact = supplier.get("impact") if isinstance(supplier.get("impact"), dict) else {}
        base_delay = pd.to_numeric(impact.get("delay_days"), errors="coerce")
        if pd.notna(base_delay):
            rv = risk_series.fillna(risk_series.median())
            rmin = float(rv.min())
            rmax = float(rv.max())
            if rmax - rmin > 1e-9:
                norm = (rv - rmin) / (rmax - rmin)
            else:
                norm = pd.Series([0.5] * len(rv), index=rv.index)
            # Keep proxy in realistic neighborhood around the latest estimated delay.
            delay_proxy = float(base_delay) * (0.75 + 0.5 * norm)
            out["delay_value"] = delay_proxy.round(4)
            used_delay_proxy = True

    # Anomaly proxy: flag spikes where absolute risk movement is unusually large.
    if anomaly_series.notna().sum() == 0 and risk_series.notna().sum() >= 3:
        rv = risk_series.ffill().bfill()
        delta = rv.diff().abs().fillna(0.0)
        threshold = float(delta.quantile(0.80))
        if threshold <= 1e-9:
            flags = pd.Series([0] * len(delta), index=delta.index)
        else:
            flags = (delta >= threshold).astype(int)
        out["anomaly_flag"] = flags
        used_anomaly_proxy = True

    return out, used_delay_proxy, used_anomaly_proxy


def _build_temporal_fallback_frame(supplier: dict[str, Any]) -> pd.DataFrame:
    impact = supplier.get("impact") if isinstance(supplier.get("impact"), dict) else {}
    risk_val = supplier.get("risk_score")
    delay_val = impact.get("delay_days") if isinstance(impact, dict) else None

    risk_num = pd.to_numeric(risk_val, errors="coerce")
    delay_num = pd.to_numeric(delay_val, errors="coerce")

    return pd.DataFrame(
        {
            "time": ["Current"],
            "risk_value": [None if pd.isna(risk_num) else float(risk_num)],
            "delay_value": [None if pd.isna(delay_num) else float(delay_num)],
            "anomaly_flag": [None],
        }
    )


def _render_temporal_page(supplier: dict[str, Any]) -> None:
    frame = _build_temporal_frame(supplier)
    if frame.empty:
        frame = _build_temporal_fallback_frame(supplier)

    frame, used_delay_proxy, used_anomaly_proxy = _derive_temporal_proxies(frame, supplier)

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Risk Score Over Time</div>", unsafe_allow_html=True)
    risk_series = pd.to_numeric(frame["risk_value"], errors="coerce")
    if risk_series.notna().any():
        fig_risk = go.Figure(
            data=[go.Scatter(x=frame["time"], y=risk_series, mode="lines+markers", name="Risk score")]
        )
        fig_risk.update_layout(xaxis_title="Time window", yaxis_title="Risk score", height=300)
        st.plotly_chart(fig_risk, width="stretch")
        valid_risk = risk_series.dropna()
        if len(valid_risk) >= 2:
            direction = "increased" if valid_risk.iloc[-1] > valid_risk.iloc[0] else "decreased"
            if valid_risk.iloc[-1] == valid_risk.iloc[0]:
                direction = "remained stable"
            st.write(f"Risk has {direction} over the observed window.")
        elif len(valid_risk) == 1:
            st.write("Temporal history is limited; showing current risk snapshot from latest output.")
    else:
        st.write("Risk trend history is not present in current outputs.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Delay Trend</div>", unsafe_allow_html=True)
    delay_series = pd.to_numeric(frame["delay_value"], errors="coerce")
    if delay_series.notna().any():
        fig_delay = go.Figure(
            data=[go.Scatter(x=frame["time"], y=delay_series, mode="lines+markers", name="Delay")]
        )
        fig_delay.update_layout(xaxis_title="Time window", yaxis_title="Delay", height=300)
        st.plotly_chart(fig_delay, width="stretch")
        if used_delay_proxy:
            st.write("Delay trend is a derived proxy from risk trajectory and current estimated delay.")
        elif len(delay_series.dropna()) == 1:
            st.write("Delay trend history is limited; showing current estimated delay from impact analysis.")
    else:
        st.write("Delay trend is not available because no delay history points were provided in outputs.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Anomaly Events</div>", unsafe_allow_html=True)
    anomaly_series = pd.to_numeric(frame["anomaly_flag"], errors="coerce")
    if anomaly_series.notna().any():
        fig_anomaly = go.Figure(
            data=[go.Bar(x=frame["time"], y=anomaly_series, name="Anomaly flag")]
        )
        fig_anomaly.update_layout(xaxis_title="Time window", yaxis_title="Anomaly flag", height=300)
        st.plotly_chart(fig_anomaly, width="stretch")
        spikes = frame.loc[anomaly_series.fillna(0) > 0, "time"].astype(str).tolist()
        if spikes:
            st.write(f"Spike detected at: {', '.join(spikes)}")
            if used_anomaly_proxy:
                st.caption("Anomaly events are inferred from large risk movements (proxy), due to missing explicit anomaly timeline.")
        else:
            st.write("No anomaly spikes detected in the available timeline.")
    else:
        st.write("No anomaly event timestamps are available in current outputs; provide timeseries anomaly flags to enable this trend.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Temporal Insights</div>", unsafe_allow_html=True)
    insights: list[str] = []

    valid_risk = risk_series.dropna()
    valid_delay = delay_series.dropna()
    valid_anomaly = anomaly_series.dropna()

    if len(valid_risk) >= 2:
        slope = float(valid_risk.iloc[-1] - valid_risk.iloc[0])
        if abs(slope) < 1e-9:
            insights.append("Risk trajectory is stable over the observed window.")
        elif slope > 0:
            insights.append(f"Risk trajectory is upward (+{slope:.3f} from first to latest point).")
        else:
            insights.append(f"Risk trajectory is downward ({slope:.3f} from first to latest point).")

    if len(valid_delay) >= 2:
        delay_delta = float(valid_delay.iloc[-1] - valid_delay.iloc[0])
        if abs(delay_delta) >= 1e-9:
            direction = "increasing" if delay_delta > 0 else "decreasing"
            insights.append(f"Delay trend is {direction} ({delay_delta:.2f} change over the window).")

    if len(valid_risk) >= 3 and len(valid_anomaly) >= 3:
        spike_count = int((valid_anomaly > 0).sum())
        if spike_count > 0:
            insights.append(f"Anomaly spikes detected in {spike_count} period(s), indicating episodic risk jumps.")

    if len(valid_risk) >= 3 and len(valid_delay) >= 3:
        aligned = pd.DataFrame({"r": risk_series, "d": delay_series}).dropna()
        if len(aligned) >= 3:
            corr = float(aligned["r"].corr(aligned["d"]))
            if pd.notna(corr):
                relation = "positive" if corr >= 0 else "negative"
                insights.append(f"Risk-delay relationship is {relation} (correlation {corr:.3f}).")

    if insights:
        for line in insights:
            st.write(f"- {line}")
    else:
        st.write("Temporal insights are limited because the required history points are not available in current outputs.")
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    _apply_styles()

    bundle = load_bundle()
    suppliers = bundle.get("suppliers") or []
    if not suppliers:
        st.error("No supplier data available. Add outputs/supplier_decision_data.json or outputs/risk_predictions.csv.")
        return

    suppliers = sorted(
        suppliers,
        key=_risk_sort_value,
        reverse=True,
    )

    _initialize_selection(suppliers)

    st.sidebar.header("Pages")
    page = st.sidebar.radio(
        "Navigate",
        ["Main Dashboard", "Proof & Validation", "Dependency Network", "Temporal Analysis"],
        index=["Main Dashboard", "Proof & Validation", "Dependency Network", "Temporal Analysis"].index(
            st.session_state.page
        ),
    )
    st.session_state.page = page

    st.sidebar.header("Filters")
    st.session_state.risk_filter = st.sidebar.selectbox(
        "Risk Level",
        ["All", "Critical", "High", "Medium", "Low"],
        index=["All", "Critical", "High", "Medium", "Low"].index(st.session_state.risk_filter),
    )
    st.session_state.supplier_query = st.sidebar.text_input(
        "Supplier Search",
        value=st.session_state.supplier_query,
        placeholder="Type supplier name...",
    )
    st.session_state.supplier_limit = st.sidebar.slider(
        "Suppliers to Show",
        min_value=5,
        max_value=50,
        value=int(st.session_state.supplier_limit),
        step=5,
    )
    st.session_state.impact_row_limit = st.sidebar.slider(
        "Impacted Rows to Show",
        min_value=5,
        max_value=8,
        value=int(st.session_state.impact_row_limit),
        step=1,
    )

    suppliers = _filter_suppliers(suppliers)
    if not suppliers:
        st.warning("No suppliers match the selected filters. Change filters to continue.")
        return

    st.markdown(
        """
        <div class="title-wrap">
            <h1>Supply Chain Decision Console</h1>
            <p>Data-backed, explainable decision support for operations and risk teams.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left_panel, main_panel = st.columns([0.95, 2.05], gap="large")

    with left_panel:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        _render_supplier_list(suppliers)
        st.markdown("</div>", unsafe_allow_html=True)

    selected = _find_selected_supplier(suppliers)
    if selected is None:
        st.warning("Select a supplier to view details.")
        return

    with main_panel:
        if page == "Main Dashboard":
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            _render_prediction(selected)
            st.markdown("</div>", unsafe_allow_html=True)
            _render_priority_alerts(selected)
            _render_why(selected)
            _render_impact(selected, selected.get("graph") or bundle.get("global_graph") or {})
            _render_recommendations(selected)
            _render_ops_ai_panel(selected)
            _render_drilldown_links()
        elif page == "Proof & Validation":
            _render_signal_validation(selected)
            _render_model_validation(selected)
        elif page == "Dependency Network":
            _render_network_page(selected, selected.get("graph") or bundle.get("global_graph") or {})
        elif page == "Temporal Analysis":
            _render_temporal_page(selected)


if __name__ == "__main__":
    main()

