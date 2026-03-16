from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.main import app
from news_analysis.finbert_analyzer import analyze_news_dataframe
from transaction_analysis.anomaly_detector import detect_transaction_anomalies


def test_transaction_analysis_interface():
    df = pd.DataFrame(
        [
            {
                "transaction_id": "TX-1",
                "company_id": "C-1",
                "supplier_id": "S-1",
                "account_id": "A-1",
                "amount": 100.0,
            },
            {
                "transaction_id": "TX-2",
                "company_id": "C-1",
                "supplier_id": "S-2",
                "account_id": "A-1",
                "amount": 99999.0,
            },
        ]
    )
    out = detect_transaction_anomalies(df)
    assert set(["transaction_id", "anomaly_score", "anomaly_flag"]).issubset(out.columns)


def test_news_analysis_interface():
    news_df = pd.DataFrame(
        [
            {
                "news_id": "N-1",
                "company_id": "C-1",
                "source": "Reuters",
                "published_at": "2026-03-12T00:00:00Z",
                "headline": "ACME faces supply chain issues",
                "body": "A lawsuit and default risk may impact supplier operations.",
            }
        ]
    )
    entities_df, events_df, sentiment_df = analyze_news_dataframe(news_df)
    assert set(["entity_id", "entity_name", "entity_type", "news_id"]).issubset(entities_df.columns)
    assert set(["event_id", "event_type", "trigger", "sentiment", "news_id"]).issubset(events_df.columns)
    assert set(["news_id", "sentiment", "sentiment_confidence", "company_id"]).issubset(sentiment_df.columns)


def test_api_pipeline_endpoints():
    client = TestClient(app)

    ingest_payload = {
        "transactions": [
            {
                "transaction_id": "TX-100",
                "company_id": "COMP-1",
                "supplier_id": "SUP-1",
                "account_id": "ACC-1",
                "amount": 1200.50,
                "currency": "USD",
                "timestamp": "2026-03-10T10:00:00Z",
                "description": "invoice payment",
            }
        ],
        "news": [
            {
                "news_id": "N-1",
                "company_id": "COMP-1",
                "source": "Reuters",
                "published_at": "2026-03-11T09:00:00Z",
                "headline": "COMP-1 hit by supply chain disruption",
                "body": "The company faces supply chain and default concerns.",
            }
        ],
    }

    r1 = client.post("/ingest_transactions", json=ingest_payload)
    assert r1.status_code == 200

    r2 = client.post("/run_graph_builder", json={"company_id": "COMP-1"})
    assert r2.status_code == 200

    r3 = client.post("/run_ml_analysis")
    assert r3.status_code == 200

    r4 = client.post("/query_agent", json={"query": "What are the key financial risks?"})
    assert r4.status_code == 200
    assert "answer" in r4.json()

    r5 = client.get("/get_alerts")
    assert r5.status_code == 200
    assert "alerts" in r5.json()
