from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd

from configs.settings import get_settings

try:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
except Exception:  # pragma: no cover
    torch = None
    AutoModelForSequenceClassification = None
    AutoTokenizer = None

LABEL_MAP = {0: "neutral", 1: "positive", 2: "negative"}
LOGGER = logging.getLogger(__name__)
EVENT_KEYWORDS = {
    "bankruptcy": "BANKRUPTCY_RISK",
    "supply chain": "SUPPLY_CHAIN_DISRUPTION",
    "lawsuit": "LEGAL_EVENT",
    "merger": "MNA_EVENT",
    "acquisition": "MNA_EVENT",
    "fraud": "FRAUD_EVENT",
    "default": "DEFAULT_RISK",
}
EVENT_BASE_IMPACT = {
    "BANKRUPTCY_RISK": 1.0,
    "DEFAULT_RISK": 0.95,
    "FRAUD_EVENT": 0.9,
    "SUPPLY_CHAIN_DISRUPTION": 0.8,
    "LEGAL_EVENT": 0.7,
    "MNA_EVENT": 0.5,
}
SECTOR_KEYWORDS = {
    "bank": "Financials",
    "insurance": "Financials",
    "oil": "Energy",
    "gas": "Energy",
    "semiconductor": "Technology",
    "software": "Technology",
    "retail": "Consumer",
    "logistics": "Industrials",
}


@lru_cache(maxsize=1)
def _load_finbert():
    settings = get_settings()
    if AutoTokenizer is None or AutoModelForSequenceClassification is None:
        return None, None

    try:
        # Prefer fast tokenizer when available, but gracefully fall back to slow mode.
        try:
            tokenizer = AutoTokenizer.from_pretrained(settings.finbert_model)
        except Exception as exc:
            LOGGER.warning("Fast tokenizer load failed, retrying with use_fast=False: %s", exc)
            tokenizer = AutoTokenizer.from_pretrained(settings.finbert_model, use_fast=False)

        model = AutoModelForSequenceClassification.from_pretrained(settings.finbert_model)
        return tokenizer, model
    except Exception as exc:
        LOGGER.warning("FinBERT load unavailable, using neutral sentiment fallback: %s", exc)
        return None, None


def _classify_entity(name: str) -> str:
    upper = name.upper()
    if "SUPPL" in upper or "VENDOR" in upper:
        return "Supplier"
    if len(upper) <= 6 and upper.isalpha():
        return "Company"
    return "Company"


def _extract_entities(text: str, news_id: str) -> list[dict[str, str]]:
    pattern = r"\b[A-Z][A-Za-z0-9&\-]{1,}\b"
    found = list(dict.fromkeys(re.findall(pattern, text)))[:30]
    entities: list[dict[str, str]] = []
    for i, token in enumerate(found):
        entity_type = _classify_entity(token)
        key = f"{entity_type.upper()}_{token}_{i}"
        entities.append(
            {
                "entity_id": key,
                "entity_name": token,
                "entity_type": entity_type,
                "news_id": news_id,
            }
        )
    lower = text.lower()
    for kw, sector in SECTOR_KEYWORDS.items():
        if kw in lower:
            entities.append(
                {
                    "entity_id": f"SECTOR_{sector}",
                    "entity_name": sector,
                    "entity_type": "Sector",
                    "news_id": news_id,
                }
            )
    return entities


def _extract_events(
    text: str,
    news_id: str,
    sentiment: str,
    linked_company_id: str | None,
    published_at: str | datetime | None,
) -> list[dict[str, Any]]:
    lower = text.lower()
    events = []
    now = datetime.now(timezone.utc)
    if published_at is None:
        event_dt = now
    else:
        event_dt = pd.to_datetime(published_at, utc=True, errors="coerce")
        if pd.isna(event_dt):
            event_dt = now
        else:
            event_dt = event_dt.to_pydatetime()

    age_days = max((now - event_dt).total_seconds() / 86400.0, 0.0)
    decay_factor = float(np.exp(-0.12 * age_days))
    sentiment_weight = {"negative": 1.0, "neutral": 0.4, "positive": 0.2}.get(sentiment, 0.4)

    for i, (key, event_type) in enumerate(EVENT_KEYWORDS.items()):
        if key in lower:
            base = EVENT_BASE_IMPACT.get(event_type, 0.5)
            impact_score = float(base * sentiment_weight * decay_factor)
            events.append(
                {
                    "event_id": f"{news_id}_{event_type}_{i}",
                    "event_type": event_type,
                    "trigger": key,
                    "sentiment": sentiment,
                    "news_id": news_id,
                    "event_timestamp": event_dt.isoformat(),
                    "event_impact_score": impact_score,
                    "event_decay_factor": decay_factor,
                    "linked_entity_type": "Company",
                    "linked_entity_id": linked_company_id or "UNKNOWN_COMPANY",
                }
            )
    return events


def analyze_news_text(financial_news_text: str) -> dict[str, Any]:
    """Input: news text. Output: entities, sentiment, events."""

    tokenizer, model = _load_finbert()
    if tokenizer is None or model is None or torch is None:
        sentiment = "neutral"
        confidence = 0.0
    else:
        inputs = tokenizer([financial_news_text], return_tensors="pt", padding=True, truncation=True)
        with torch.no_grad():
            logits = model(**inputs).logits
        probs = torch.softmax(logits, dim=1)[0]
        label_idx = int(torch.argmax(probs).item())
        sentiment = LABEL_MAP.get(label_idx, "neutral")
        confidence = float(probs[label_idx].item())

    entities = _extract_entities(financial_news_text, news_id="TEXT_INPUT")
    events = _extract_events(
        financial_news_text,
        news_id="TEXT_INPUT",
        sentiment=sentiment,
        linked_company_id=None,
        published_at=None,
    )

    return {
        "entities": [e["entity_name"] for e in entities],
        "sentiment": sentiment,
        "sentiment_confidence": round(confidence, 6),
        "events": events,
    }


def analyze_news_dataframe(news_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Analyze news dataframe with FinBERT and return graph-compatible records.

    Returns:
    - entities_df: entity_id, entity_name, entity_type, news_id
    - events_df: event_id, event_type, trigger, sentiment, news_id, linked_entity_type, linked_entity_id
    - sentiment_df: news_id, sentiment, sentiment_confidence, company_id, published_at
    """
    if news_df.empty:
        return (
            pd.DataFrame(columns=["entity_id", "entity_name", "entity_type", "news_id"]),
            pd.DataFrame(
                columns=[
                    "event_id",
                    "event_type",
                    "trigger",
                    "sentiment",
                    "news_id",
                    "linked_entity_type",
                    "linked_entity_id",
                ]
            ),
            pd.DataFrame(columns=["news_id", "sentiment", "sentiment_confidence", "company_id"]),
        )

    entities_out: list[dict[str, str]] = []
    events_out: list[dict[str, str]] = []
    sentiment_rows: list[dict[str, Any]] = []

    for row in news_df.to_dict(orient="records"):
        news_id = str(row.get("news_id", "UNKNOWN_NEWS"))
        company_id = row.get("company_id")
        text = f"{row.get('headline', '')}. {row.get('body', '')}".strip()
        single = analyze_news_text(text)

        sentiment_rows.append(
            {
                "news_id": news_id,
                "sentiment": single.get("sentiment", "neutral"),
                "sentiment_confidence": single.get("sentiment_confidence", 0.0),
                "company_id": company_id,
                "published_at": row.get("published_at"),
            }
        )

        entities_out.extend(_extract_entities(text, news_id=news_id))
        events_out.extend(
            _extract_events(
                text,
                news_id=news_id,
                sentiment=single.get("sentiment", "neutral"),
                linked_company_id=company_id,
                published_at=row.get("published_at"),
            )
        )

    entities_df = pd.DataFrame(entities_out).drop_duplicates().reset_index(drop=True)
    events_df = pd.DataFrame(events_out).drop_duplicates().reset_index(drop=True)
    sentiment_df = pd.DataFrame(sentiment_rows).drop_duplicates().reset_index(drop=True)
    LOGGER.info(
        "News analysis complete: %s entity records, %s event records",
        len(entities_df),
        len(events_df),
    )
    return entities_df, events_df, sentiment_df
