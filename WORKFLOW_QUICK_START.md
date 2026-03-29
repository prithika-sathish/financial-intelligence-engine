# Supply Chain Risk Workflow - Quick Reference

## ✅ What Was Implemented

### 1. **Recommendation Engine** (`workflow/recommendation_engine.py`)
Generates context-aware explanations for supplier decisions.

**Inputs:**
- Risk score
- Cost impact  
- Criticality/systemic importance
- Recommended action

**Output:** Human-readable recommendation text

**Example:**
```
Supplier COMP-0 is flagged as critical risk and critical to the supply chain.

Key concerns:
  1. Risk score at 0.82 indicates significant exposure
  2. Cost impact of ₹2.7M would significantly affect operations
  3. Affects multiple critical downstream dependencies

STATUS: Immediate action required.
RECOMMENDATION: Initiate supplier replacement process immediately...
```

---

### 2. **Email Alert Module** (`workflow/email_notifier.py`)
Sends risk alerts for high-risk suppliers.

**Trigger:** `risk_score > 0.6 OR cost_impact > 0.6`

**Alert Limits:** Top 5 riskiest suppliers (safety feature)

**Delivery Methods:**
- **Simulated** (default) - Logs alerts to `logs/pipeline.log`
- **Email** (optional) - Requires SMTP config

**Alert Includes:**
- Risk metrics
- Cost impact estimate
- Key risk factors
- Recommended action
- Simulation insights

---

### 3. **Portfolio State Tracker** (`workflow/portfolio_tracker.py`)
Tracks supplier status and health metrics.

**Status Levels:**
```
High Risk:  risk_score > 0.7
Watchlist:  0.4 < risk_score ≤ 0.7
Stable:     risk_score ≤ 0.4
```

**Outputs:**
- `portfolio_state.csv` - Individual supplier status
- `portfolio_summary.json` - Aggregate metrics

**Enables:**
- Audit trails
- Historical comparisons
- Portfolio health dashboards

---

## 📊 Data Flow

```
run_pipeline.py (main)
    ↓
Stage 9: Decision Engine
  (risk, cost, criticality, actions)
    ↓
Stage 9b: Workflow ← NEW
  ├─ Generate recommendations
  ├─ Track portfolio state
  └─ Send top 5 alerts
    ↓
Stage 10-11: Agent reasoning + Output persistence
    ↓
Outputs:
  • risk_predictions.csv (with recommendation_text)
  • portfolio_state.csv (with statuses)
  • portfolio_summary.json (health metrics)
  • Alert logs (in logs/pipeline.log)
```

---

## 🚀 Running the Pipeline

### Default (Simulated Alerts)
```bash
cd financial_intelligence_engine
python run_pipeline.py
```

**Output:**
- All supplier recommendations generated
- Portfolio state saved
- Alerts logged (not emailed)
- Workflow time: ~2-5 seconds

### With Real Email Alerts (Optional)
```bash
# 1. Set environment variables
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=your-email@gmail.com
export SMTP_PASSWORD=your-app-password

# 2. Edit run_pipeline.py:
#    Line 316: simulate=True → simulate=False

# 3. Run pipeline
python run_pipeline.py
```

---

## 📁 Output Files

| File | Purpose | When Created |
|------|---------|--------------|
| `outputs/portfolio_state.csv` | Supplier status tracking | Stage 9b |
| `outputs/portfolio_summary.json` | Portfolio health metrics | Stage 11 |
| `outputs/risk_predictions.csv` | Predictions + recommendations | Stage 11 |
| `logs/pipeline.log` | Alert logs + workflow traces | Always |

---

## 📋 Portfolio State CSV Structure

```csv
supplier_id,last_risk_score,last_cost_impact,last_action,status,criticality,updated_at
COMP-0,0.82,0.75,Replace supplier,high_risk,0.68,2026-03-29T15:45:32.123456
COMP-1,0.45,0.35,Diversify suppliers,watchlist,0.42,2026-03-29T15:45:32.123456
COMP-2,0.22,0.15,Monitor,stable,0.18,2026-03-29T15:45:32.123456
```

---

## 📊 Portfolio Summary JSON Structure

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

## 🔍 Log Output Examples

**Recommendation Generation:**
```
Stage 9b/11 start: workflow - recommendations and alerts
Generated recommendations for 45 suppliers
```

**Portfolio Tracking:**
```
Portfolio state saved to outputs/portfolio_state.csv | total_suppliers=45
Portfolio status distribution: {'stable': 34, 'watchlist': 8, 'high_risk': 3}
```

**Alert Simulation:**
```
ALERT (SIMULATED): COMP-0 | Risk: 0.82 | Cost Impact: 0.75
ALERT (SIMULATED): COMP-3 | Risk: 0.78 | Cost Impact: 0.68
ALERT (SIMULATED): COMP-5 | Risk: 0.72 | Cost Impact: 0.65
ALERT (SIMULATED): COMP-12 | Risk: 0.68 | Cost Impact: 0.60
ALERT (SIMULATED): COMP-8 | Risk: 0.65 | Cost Impact: 0.58
```

**Alerts Sent Summary:**
```
Stage 9b/11 end: workflow complete | alerts_sent=5 portfolio_suppliers=45 duration_sec=0.342
```

---

## 🎯 Key Design Principles

✅ **Lightweight** - No heavy dependencies or external APIs
✅ **Safe** - Email simulation by default, requires explicit config to send real emails
✅ **Integrated** - Seamlessly fits into existing pipeline as Stage 9b
✅ **Observable** - Complete logging of all operations
✅ **Optional** - Can disable workflow without affecting other stages
✅ **Audit-ready** - Portfolio state provides compliance trail

---

## 🛡️ Safety Features

1. **Email Limits** - Only top 5 suppliers get alerts
2. **Simulation by Default** - Must explicitly enable real emails
3. **Trigger Thresholds** - Alerts only when risk > 0.6 or cost > 0.6
4. **Graceful Fallback** - If SMTP fails, logs alert instead of crashing
5. **Error Handling** - Missing data filled with sensible defaults

---

## 📈 Workflow Metrics

**Portfolio Summary Provides:**
- Total supplier count
- Risk distribution (high/watchlist/stable)
- Average risk and criticality
- High-criticality supplier count

**Use Cases:**
- Board reporting on supplier risk
- Compliance audits
- SLA tracking
- Risk trend analysis

---

## 🔧 Customization Options

**Easy to modify:**
- Alert thresholds (email_notifier.py line 62-63)
- Top N alert limit (run_pipeline.py line 316)
- Status definitions (portfolio_tracker.py line 22-30)
- Recommendation logic (recommendation_engine.py)

**No code changes needed:**
- Change email recipients (via environment variables)
- Enable/disable alerts (simulate=True/False)
- Save schedule (integrated into pipeline)

---

## ✨ Example Use Case

**Scenario:** Daily supply chain risk report

**Process:**
1. Run `python run_pipeline.py` at 9 AM
2. Top 5 risky suppliers logged
3. Portfolio state saved for dashboard
4. Recommendations available in CSV
5. Emails sent to procurement team (if configured)

**Result:**
- Team sees who needs attention
- Historical state tracked
- Actions documented
- Audit trail complete

---

## 📚 Files Reference

| File | Lines | Purpose |
|------|-------|---------|
| `workflow/recommendation_engine.py` | 100 | Generate human-readable recommendations |
| `workflow/email_notifier.py` | 180 | Send and simulate email alerts |
| `workflow/portfolio_tracker.py` | 140 | Track supplier status and health |
| `run_pipeline.py` | Updated @ Stage 9b | Integration point |

---

## 🚦 Status

✅ Implemented
✅ Integrated into pipeline
✅ Tested with sample data
✅ Logging configured
✅ Error handling in place
✅ Documentation complete

---

## 📞 Questions?

See `WORKFLOW_INTEGRATION_GUIDE.md` for detailed documentation.

