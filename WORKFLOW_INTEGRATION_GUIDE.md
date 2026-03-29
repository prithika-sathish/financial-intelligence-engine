# Workflow Layer Integration Guide

## Overview

A lightweight workflow layer has been added to the supply chain risk intelligence system. This layer generates context-aware recommendations, sends email alerts for high-risk suppliers, and tracks portfolio state—all without complex integrations.

## Components Added

### 1. **workflow/recommendation_engine.py**

Generates human-readable recommendations based on supplier risk profiles.

**Key functions:**
- `generate_recommendation(row)` - Creates actionable recommendation text
- `enrich_predictions_with_recommendations(predictions_df)` - Adds `recommendation_text` column to dataframe

**Output Example:**
```
Supplier COMP-0 is flagged as critical risk and critical to the supply chain.

Key concerns:
  1. Risk score at 0.82 indicates significant exposure
  2. Cost impact of ₹2.7M would significantly affect operations
  3. Affects multiple critical downstream dependencies

STATUS: Immediate action required.
RECOMMENDATION: Initiate supplier replacement process immediately. 
Cost of failure (very high) justifies transition costs. 
Begin identifying alternative suppliers and transitioning volume.
```

---

### 2. **workflow/email_notifier.py**

Sends context-aware email alerts for high-risk suppliers.

**Trigger Conditions:**
```
Send email if: risk_score > 0.6 OR estimated_cost_impact > 0.6
```

**Key functions:**
- `send_supplier_alert(row, to_email=None, simulate=True)` - Sends alert for single supplier
- `send_top_supplier_alerts(predictions_df, top_n=5, simulate=True)` - Sends alerts for top N risky suppliers

**Email Content:**
- Supplier name and risk metrics
- Estimated cost impact
- Criticality assessment
- Key risk factors
- Recommended action
- Simulation insight

**Configuration:**
```bash
# Optional SMTP setup (for real email sending):
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=your-email@gmail.com
export SMTP_PASSWORD=your-app-password
export FROM_EMAIL=alerts@yourcompany.com
```

**Default Behavior:**
- If SMTP not configured or `simulate=True`, alerts are logged instead
- Logs appear in `logs/pipeline.log`
- Safe for local development

---

### 3. **workflow/portfolio_tracker.py**

Tracks supplier status and portfolio health metrics.

**Status Mapping:**
```
risk_score > 0.7  → "high_risk"
risk_score > 0.4  → "watchlist"
risk_score ≤ 0.4  → "stable"
```

**Key functions:**
- `track_portfolio_state(predictions_df, output_dir)` - Creates portfolio state tracking
- `get_portfolio_summary(portfolio_df)` - Generates summary metrics
- `compare_portfolio_states(previous_state, current_state)` - Detects changes

**Output File:** `outputs/portfolio_state.csv`

**Columns:**
| Column | Description |
|--------|-------------|
| supplier_id | Unique supplier identifier |
| last_risk_score | Latest risk score (0-1) |
| last_cost_impact | Estimated cost impact |
| last_action | Recommended action |
| status | high_risk / watchlist / stable |
| criticality | Systemic importance (0-1) |
| updated_at | ISO timestamp |

**Portfolio Summary:** `outputs/portfolio_summary.json`

```json
{
  "total_suppliers": 45,
  "high_risk_count": 3,
  "watchlist_count": 8,
  "stable_count": 34,
  "avg_risk_score": 0.42,
  "avg_criticality": 0.35,
  "high_criticality_suppliers": 2
}
```

---

## Pipeline Integration

The workflow layer is integrated into `run_pipeline.py` as **Stage 9b** (between decision-support enrichment and agent reasoning):

```
Stage 9:   Decision-Support Enrichment
           ↓
Stage 9b:  Workflow (NEW)
           • Generate recommendations
           • Track portfolio state
           • Send alerts for top 5 suppliers
           ↓
Stage 10:  Agent Reasoning
Stage 11:  Output Persistence
```

### What Happens at Stage 9b:

1. **Recommendation Generation**
   - Analyzes risk, cost, and criticality
   - Creates human-readable explanations
   - Adds `recommendation_text` column to output

2. **Portfolio Tracking**
   - Saves `portfolio_state.csv` with all suppliers
   - Generates summary metrics
   - Logs portfolio health

3. **Alert Generation**
   - Identifies top 5 risky suppliers
   - Sends simulated alerts (or real emails if configured)
   - Returns alert results for logging

---

## Output Files

After pipeline runs, the following workflow files are generated in `outputs/`:

| File | Purpose | Format |
|------|---------|--------|
| `risk_predictions.csv` | Main predictions with recommendations | CSV |
| `portfolio_state.csv` | Supplier status tracking | CSV |
| `portfolio_summary.json` | Portfolio health metrics | JSON |

---

## Usage Examples

### Run Pipeline (Alerts Simulated)
```bash
cd financial_intelligence_engine
python run_pipeline.py
```

This will:
- Generate recommendations for all suppliers
- Log simulated alerts for top 5 risky suppliers
- Save portfolio state to CSV
- Include all data in returned JSON

**Log Output:**
```
Stage 9b/11 start: workflow - recommendations and alerts
Generated recommendations for 45 suppliers
ALERT (SIMULATED): COMP-0 | Risk: 0.82 | Cost Impact: 0.75
ALERT (SIMULATED): COMP-3 | Risk: 0.78 | Cost Impact: 0.68
...
Stage 9b/11 end: workflow complete | alerts_sent=5 portfolio_suppliers=45
```

### Enable Real Email Alerts (Optional)
```bash
# 1. Configure SMTP environment variables
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=your-email@gmail.com
export SMTP_PASSWORD=your-app-password

# 2. Modify run_pipeline.py to disable simulation:
#    Change: send_top_supplier_alerts(..., simulate=True)
#    To:     send_top_supplier_alerts(..., simulate=False)

# 3. Run pipeline
python run_pipeline.py
```

---

## Key Features

✅ **Lightweight** - No external APIs or complex integrations
✅ **Safe** - Alerts simulated by default with email config optional
✅ **Actionable** - Recommendations guide decision-making
✅ **Tracked** - Portfolio state saved for audit trails
✅ **Integrated** - Seamlessly fits into existing pipeline
✅ **Observable** - Detailed logging of all workflow operations

---

## Sample Output

### Recommendation Text (In CSV)
```
Supplier COMP-0 is flagged as critical risk and critical to the supply chain.

Key concerns:
  1. Risk score at 0.82 indicates significant exposure
  2. Cost impact of ₹2.7M would significantly affect operations
  3. Affects multiple critical downstream dependencies

STATUS: Immediate action required.
RECOMMENDATION: Initiate supplier replacement process immediately. 
Cost of failure (very high) justifies transition costs. 
Begin identifying alternative suppliers and transitioning volume.
```

### Alert Log (In logs/pipeline.log)
```
2026-03-29T10:45:32 | INFO | workflow.email | ALERT (SIMULATED): COMP-0 | Risk: 0.82 | Cost Impact: 0.75
2026-03-29T10:45:32 | INFO | workflow.portfolio | Portfolio state saved to outputs/portfolio_state.csv | total_suppliers=45
2026-03-29T10:45:32 | INFO | workflow.portfolio | Portfolio status distribution: {'stable': 34, 'watchlist': 8, 'high_risk': 3}
```

### Portfolio State (CSV)
```
supplier_id,last_risk_score,last_cost_impact,last_action,status,criticality,updated_at
COMP-0,0.82,0.75,Replace supplier,high_risk,0.68,2026-03-29T15:45:32.123456
COMP-1,0.45,0.35,Diversify suppliers,watchlist,0.42,2026-03-29T15:45:32.123456
COMP-2,0.22,0.15,Monitor,stable,0.18,2026-03-29T15:45:32.123456
```

---

## Architecture Diagram

```
run_pipeline.py
    │
    ├─ Stage 1-9: Existing pipeline
    │
    └─ Stage 9b: Workflow Layer (NEW)
         │
         ├─ recommendation_engine.py
         │  └─ generate_recommendation() → recommendation_text
         │
         ├─ portfolio_tracker.py
         │  ├─ track_portfolio_state() → portfolio_state.csv
         │  └─ get_portfolio_summary() → portfolio_summary.json
         │
         └─ email_notifier.py
            └─ send_top_supplier_alerts() → [logs | emails]
                (simulated by default)
    │
    ├─ Stage 10-11: Existing output persistence
    │
    └─ Return workflow data to caller
```

---

## Notes

- **Recommendations** are deterministic and based on risk, cost, and criticality metrics
- **Alerts** are limited to top 5 suppliers for safety and relevance
- **Portfolio tracking** creates an audit trail of supplier status changes
- **Email simulation** is default for safety; no configuration needed
- All **workflow modules are optional** - removing them doesn't break the pipeline

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Empty predictions | Returns empty alert list, no errors |
| Missing columns | Gracefully fills with defaults (0.0, "Unknown") |
| SMTP not configured | Logs alert instead of sending email |
| Email sending fails | Logs warning, continues pipeline |
| Invalid risk scores | Normalized to 0-1 range |

---

## Testing

Quick validation:
```bash
# Run pipeline and check outputs
python run_pipeline.py

# Verify workflow outputs exist
ls -la outputs/portfolio_state.csv
ls -la outputs/portfolio_summary.json

# Check alert logs
tail -20 logs/pipeline.log | grep "ALERT\|Portfolio\|workflow"
```

---

## Future Enhancements (Optional)

- Slack/Teams integration for alerts
- Dashboard with portfolio visualizations
- Historical state comparison and trend analysis
- Customizable alert thresholds
- Supplier communication templates
- Automated escalation workflows

