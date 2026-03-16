# Fin-IQ: Financial Intelligence Engine

An AI system that detects emerging financial risk by combining transaction anomaly detection, financial news intelligence, temporal trend modeling, and supplier dependency graph propagation.

## 1. System Architecture

### Pipeline Overview (10 Stages)

Raw Data  
-> Transaction Anomaly Detection  
-> Financial News Analysis (FinBERT)  
-> Knowledge Graph Construction  
-> Temporal Risk Analysis  
-> Feature Engineering  
-> ML Risk Prediction  
-> Dependency Risk Propagation  
-> AI Agent Reasoning  
-> Alerts and Reports

### Architecture Diagram

```text
sample_data/{transactions,news}
        |
        v
[1] data_ingestion
        |
        v
[2] transaction_analysis (anomaly)
        |
        v
[3] news_analysis (FinBERT + events)
        |
        v
[4] graph_engine (Neo4j optional)
        |
        v
[5] ml_models.temporal_analyzer
        |
        v
[6] ml_models.feature_extractor
        |
        v
[7] ml_models.risk_model
        |
        v
[8] ml_models.dependency_propagation
        |
        v
[9] agent_system.graph_agent
        |
        v
[10] outputs/*.csv + outputs/*.json
```

## 2. Core Components

- Data Ingestion: validates and normalizes transaction/news records into pandas DataFrames.
- Transaction Analysis: computes anomaly scores from rolling-window behavioral features.
- News Intelligence: uses FinBERT sentiment + event/entity extraction for financial signal capture.
- Graph Engine: builds financial relationship context and persists to Neo4j when available.
- Temporal Risk Modeling: computes rolling exposure, velocity, and acceleration trends per company.
- ML Risk Classifier: predicts company-level exposure scores using engineered multi-source features.
- Dependency Propagation: spreads risk through supplier/partner dependency links.
- Agent Reasoning: produces analyst-facing answers and alert narratives with evidence.
- API Layer: FastAPI endpoints for staged execution and interactive querying.
- Visualization: Streamlit dashboard for interactive exploration of all pipeline layers.

## 3. Unified Project Structure

```text
financial_intelligence_engine/
  data_ingestion/
  transaction_analysis/
  news_analysis/
  graph_engine/
  ml_models/
  agent_system/
  visualization/
  api/
  sample_data/
  outputs/
  models/
  docs/
  README.md
  requirements.txt
  run_pipeline.py
  dashboard.py
```

## 4. Input Data Format

### Transactions Schema

| Field | Type | Required | Description |
|---|---|---|---|
| transaction_id | string | yes | Unique transaction identifier |
| company_id | string | yes | Company receiving or issuing transaction |
| supplier_id | string | yes | Supplier/counterparty identifier |
| account_id | string | yes | Account identifier |
| amount | number | yes | Transaction amount |
| currency | string | no | Currency code, default USD |
| timestamp | datetime | yes | ISO-8601 timestamp |
| description | string | no | Free-text description |

### News Schema

| Field | Type | Required | Description |
|---|---|---|---|
| news_id | string | yes | Unique article identifier |
| company_id | string/null | no | Linked company identifier |
| source | string | no | News provider |
| published_at | datetime | yes | ISO-8601 publication timestamp |
| headline | string | yes | Article headline |
| body | string | yes | Article text |

### Example Transaction JSON

```json
[
  {
    "transaction_id": "TX-001",
    "company_id": "COMP-ALPHA",
    "supplier_id": "SUP-STEEL",
    "account_id": "ACC-ALPHA-1",
    "amount": 145000.0,
    "currency": "USD",
    "timestamp": "2026-03-12T01:20:00Z",
    "description": "Late-night emergency steel procurement"
  }
]
```

### Example News JSON

```json
[
  {
    "news_id": "NEWS-001",
    "company_id": "COMP-ALPHA",
    "source": "Reuters",
    "published_at": "2026-03-12T05:00:00Z",
    "headline": "COMP ALPHA faces supply chain disruption",
    "body": "Supplier stress and legal pressure may impact operations."
  }
]
```

## 5. Pipeline Outputs

- outputs/anomaly_scores.csv: transaction-level anomaly score and binary anomaly flag.
- outputs/entities.csv: extracted entities from financial news.
- outputs/events.csv: extracted event records with timestamps and impact scores.
- outputs/features.csv: per-company engineered feature frame used by ML scoring.
- outputs/risk_predictions.csv: base and systemic company exposure classification outputs.
- outputs/risk_trends.csv: trend direction, velocity, acceleration, and risk history snapshots.
- outputs/network_risk_analysis.csv: dependency-propagated exposure and network vulnerability metrics.
- outputs/risk_trends.json: compact trend summary payload for UI/API use.
- outputs/network_risk_analysis.json: compact network risk payload for UI/API use.

## 6. Risk Interpretation Guide

- risk_score: base model output for company exposure likelihood.
  - Example: 0.62 indicates elevated baseline concern.
- risk_level: bucketed label (low/medium/high) from score bands.
  - Example: medium suggests monitoring and analyst review.
- propagated_risk: score after dependency contagion effects.
  - Example: 0.42 -> 0.58 means network amplified exposure.
- network_exposure_score: direct dependency-driven vulnerability measure.
  - Example: 0.22 indicates meaningful contagion sensitivity.
- systemic_importance_score: graph centrality-style importance in the ecosystem.
  - Example: high score means broader downstream impact if distressed.
- risk_velocity: first derivative of risk over time.
  - Example: positive velocity indicates worsening trend.
- risk_acceleration: second derivative of risk over time.
  - Example: positive acceleration means risk is worsening faster.

## 7. Running the System

### Install

```bash
pip install -r requirements.txt
```

### Run Pipeline

```bash
python run_pipeline.py
```

### Run Dashboard

```bash
streamlit run dashboard.py
```

## 8. Example Output

```json
{
  "company_id": "COMP-BETA",
  "risk_score": 0.2379,
  "propagated_risk": 0.4273,
  "risk_level": "medium",
  "systemic_importance_score": 0.3421,
  "network_exposure_score": 0.2208,
  "risk_trend": "stable",
  "risk_velocity": 0.0
}
```

## 9. AI Capabilities

- FinBERT: financial sentiment analysis over headlines/articles.
- Groq LLM agent: grounded risk explanation and analyst query answering.

Example analyst queries:
- Which companies show increasing financial risk?
- Which suppliers create contagion risk?
- What events triggered risk for COMP-ALPHA?

## 10. Visualization Layer

The Streamlit dashboard provides:
- risk leaderboard
- dependency network graph
- risk trend visualization
- transaction anomaly analysis
- AI query interface

## 11. Limitations

- Uses sample data by default.
- Graph database persistence is optional (dry-run when Neo4j unavailable).
- Risk labels are approximated from proxy targets rather than audited ground truth labels.

## 12. Future Improvements

- real financial data ingestion connectors
- live market/news feed integration
- real-time risk monitoring and streaming alerts
- stronger contagion and causal dependency modeling
