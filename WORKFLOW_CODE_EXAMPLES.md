# Workflow Layer - Code Examples & Best Practices

## 📚 Complete Code Examples

### Example 1: Generate Recommendations for All Suppliers

```python
from workflow.recommendation_engine import enrich_predictions_with_recommendations
import pandas as pd

# Load predictions
predictions_df = pd.read_csv('outputs/risk_predictions.csv')

# Add recommendations
recommendations_df = enrich_predictions_with_recommendations(predictions_df)

# Save with recommendations
recommendations_df.to_csv('outputs/risk_predictions_with_recommendations.csv', index=False)

# Access recommendation text
for idx, row in recommendations_df.iterrows():
    print(f"\n{row['company_id']}:")
    print(row['recommendation_text'])
```

**Output:**
```
COMP-0:
Supplier COMP-0 is flagged as critical risk and critical to the supply chain.

Key concerns:
  1. Risk score at 0.82 indicates significant exposure
  2. Cost impact of ₹2.7M would significantly affect operations
  3. Affects multiple critical downstream dependencies

STATUS: Immediate action required.
RECOMMENDATION: Initiate supplier replacement process immediately...
```

---

### Example 2: Send Alerts for Top 5 Suppliers

```python
from workflow.email_notifier import send_top_supplier_alerts
import pandas as pd

# Load predictions
predictions_df = pd.read_csv('outputs/risk_predictions.csv')

# Send alerts (simulated)
alert_results = send_top_supplier_alerts(
    predictions_df,
    top_n=5,
    simulate=True  # Set to False for real emails
)

# Process results
for alert in alert_results:
    print(f"Rank {alert['rank']}: {alert['company_id']}")
    print(f"  Method: {alert['method']}")
    print(f"  Status: {'Sent' if alert['sent'] else 'Failed'}")
```

---

### Example 3: Track Portfolio State

```python
from workflow.portfolio_tracker import (
    track_portfolio_state,
    get_portfolio_summary,
    compare_portfolio_states
)
from pathlib import Path
import pandas as pd

# Load current predictions
predictions_df = pd.read_csv('outputs/risk_predictions.csv')

# Create portfolio state
output_dir = Path('outputs')
portfolio_df = track_portfolio_state(predictions_df, output_dir)

# Get summary
summary = get_portfolio_summary(portfolio_df)

print(f"Total suppliers: {summary['total_suppliers']}")
print(f"High risk: {summary['high_risk_count']}")
print(f"Watchlist: {summary['watchlist_count']}")
print(f"Stable: {summary['stable_count']}")

# Compare with previous state
previous_state = pd.read_csv('outputs/previous_portfolio_state.csv')
changes = compare_portfolio_states(previous_state, portfolio_df)

print(f"\nChanges since last run:")
print(f"  Improvements: {changes['improvements']}")
print(f"  Deteriorations: {changes['deteriorations']}")
print(f"  Status changes: {changes['status_changes']}")
```

---

### Example 4: Full Integration (As in run_pipeline.py)

```python
from workflow.email_notifier import send_top_supplier_alerts
from workflow.recommendation_engine import enrich_predictions_with_recommendations
from workflow.portfolio_tracker import track_portfolio_state, get_portfolio_summary
import pandas as pd
from pathlib import Path

# After decision_engine produces predictions_df
predictions_df = recomm_actions(predictions_df)  # Stage 9

# Stage 9b: Workflow
print("Generating recommendations...")
predictions_df = enrich_predictions_with_recommendations(predictions_df)

print("Tracking portfolio state...")
output_dir = Path('outputs')
portfolio_df = track_portfolio_state(predictions_df, output_dir)
portfolio_summary = get_portfolio_summary(portfolio_df)

print("Sending alerts...")
alert_results = send_top_supplier_alerts(
    predictions_df,
    top_n=5,
    simulate=True
)

# Log results
print(f"✓ Recommendations: {len(predictions_df)} suppliers")
print(f"✓ Portfolio tracked: {len(portfolio_df)} suppliers")
print(f"✓ Alerts sent: {len(alert_results)} alerts")

# Continue with agent reasoning...
agent_result = run_agent(...)  # Stage 10
```

---

### Example 5: Enable Real Email Alerts

```python
import os
from workflow.email_notifier import send_supplier_alert
import pandas as pd

# Configure SMTP environment
os.environ['SMTP_HOST'] = 'smtp.gmail.com'
os.environ['SMTP_PORT'] = '587'
os.environ['SMTP_USER'] = 'alerts@company.com'
os.environ['SMTP_PASSWORD'] = 'app-specific-password'
os.environ['FROM_EMAIL'] = 'alerts@company.com'

# Load predictions
predictions_df = pd.read_csv('outputs/risk_predictions.csv')

# Send alert to specific email
for idx, row in predictions_df.nlargest(3, 'propagated_risk').iterrows():
    result = send_supplier_alert(
        row,
        to_email='procurement@company.com',
        simulate=False  # REAL EMAIL
    )
    
    if result['sent']:
        print(f"✓ Email sent for {result['company_id']}")
    else:
        print(f"✗ Failed to send for {result['company_id']}")
```

---

### Example 6: Custom Risk Level Thresholds

```python
from workflow.email_notifier import send_supplier_alert
import pandas as pd

# Load predictions
predictions_df = pd.read_csv('outputs/risk_predictions.csv')

# Custom alert logic
alerts_sent = []
for idx, row in predictions_df.iterrows():
    risk = float(row.get('propagated_risk', 0.0))
    cost = float(row.get('estimated_cost_impact', 0.0))
    
    # Custom trigger: very high risk OR very high cost
    should_alert = (risk > 0.75) or (cost > 0.75)
    
    if should_alert:
        result = send_supplier_alert(
            row,
            to_email='team@company.com',
            simulate=True
        )
        alerts_sent.append(result)

print(f"Custom alerts sent: {len(alerts_sent)}")
```

---

### Example 7: Generate Recommendation Report

```python
from workflow.recommendation_engine import generate_recommendation
import pandas as pd

# Load predictions
predictions_df = pd.read_csv('outputs/risk_predictions.csv')

# Generate report
report = []
for idx, row in predictions_df.iterrows():
    supplier_id = row['company_id']
    risk = float(row.get('propagated_risk', 0.0))
    
    if risk > 0.5:  # Only report on risky suppliers
        recommendation = generate_recommendation(row)
        report.append({
            'supplier_id': supplier_id,
            'risk_score': risk,
            'recommendation': recommendation
        })

# Save report
with open('outputs/supplier_recommendations_report.txt', 'w') as f:
    for item in report:
        f.write(f"\n{'='*60}\n")
        f.write(f"SUPPLIER: {item['supplier_id']}\n")
        f.write(f"RISK SCORE: {item['risk_score']:.2f}\n")
        f.write(f"{'='*60}\n")
        f.write(item['recommendation'])
        f.write("\n")

print(f"Report generated: {len(report)} suppliers")
```

---

## 🏆 Best Practices

### 1. Always Use Propagated Risk

```python
# ✅ GOOD
risk_col = "propagated_risk" if "propagated_risk" in df.columns else "risk_score"
risk = pd.to_numeric(df[risk_col], errors='coerce').fillna(0.0)

# ❌ AVOID
risk = df['risk_score']  # May not be available
```

---

### 2. Handle Missing Columns Gracefully

```python
# ✅ GOOD
company_id = row.get("company_id", "Unknown")
cost_impact = float(row.get("estimated_cost_impact", 0.0))

# ❌ AVOID
company_id = row["company_id"]  # KeyError if missing
cost_impact = row["estimated_cost_impact"]  # May cause errors
```

---

### 3. Log Workflow Operations

```python
import logging

logger = logging.getLogger("workflow")

# ✅ GOOD - Informative logging
logger.info("Generated recommendations for %d suppliers", len(df))
logger.debug("Top 5 alerts: %s", [a['company_id'] for a in alert_results[:5]])

# ❌ AVOID
print("Done")  # Hard to find in logs
```

---

### 4. Simulate Before Going Live

```python
# ✅ GOOD - Test with simulation
alert_results = send_top_supplier_alerts(
    predictions_df,
    top_n=5,
    simulate=True  # See output in logs first
)

# Later, enable real emails:
# simulate=False  # Only after testing
```

---

### 5. Check Portfolio Health Regularly

```python
# ✅ GOOD - Monitor trends
summary = get_portfolio_summary(portfolio_df)

if summary['high_risk_count'] > 5:
    logger.warning("Portfolio has %d high-risk suppliers", 
                   summary['high_risk_count'])

if summary['avg_criticality'] > 0.5:
    logger.warning("Average criticality is high: %.2f", 
                   summary['avg_criticality'])
```

---

### 6. Audit Trail Best Practice

```python
# ✅ GOOD - Compare states for audit
previous_state = pd.read_csv('outputs/previous_portfolio_state.csv')
current_state = pd.read_csv('outputs/portfolio_state.csv')

changes = compare_portfolio_states(previous_state, current_state)

# Log for compliance
logger.info("Portfolio changes: improvements=%d deteriorations=%d status_changes=%d",
            changes['improvements'],
            changes['deteriorations'],
            changes['status_changes'])

# Save comparison
with open('outputs/portfolio_changes.txt', 'w') as f:
    f.write(f"Improvements: {changes['improvements']}\n")
    f.write(f"Deteriorations: {changes['deteriorations']}\n")
    f.write(f"Status changes: {changes['status_changes']}\n")
```

---

### 7. Error Handling Pattern

```python
# ✅ GOOD - Robust error handling
try:
    alert_results = send_top_supplier_alerts(predictions_df, top_n=5)
    logger.info("Alerts sent successfully: %d", len(alert_results))
except Exception as e:
    logger.error("Error sending alerts: %s", str(e))
    # Continue execution, don't crash
    alert_results = []

# Continue with next stage
portfolio_df = track_portfolio_state(predictions_df, output_dir)
```

---

## 🔍 Debugging Tips

### Check if Recommendations Were Generated

```python
import pandas as pd

df = pd.read_csv('outputs/risk_predictions.csv')

# Verify column exists
if 'recommendation_text' in df.columns:
    print("✓ Recommendations present")
    print(f"  Sample: {df['recommendation_text'].iloc[0][:100]}...")
else:
    print("✗ Recommendations missing")
```

---

### Verify Portfolio State

```python
import pandas as pd

portfolio = pd.read_csv('outputs/portfolio_state.csv')

# Check distribution
print("Status distribution:")
print(portfolio['status'].value_counts())

# Check dates
print("\nLatest update:", portfolio['updated_at'].max())

# Check high-risk suppliers
high_risk = portfolio[portfolio['status'] == 'high_risk']
print(f"\nHigh-risk suppliers ({len(high_risk)}):")
for _, row in high_risk.iterrows():
    print(f"  {row['supplier_id']}: {row['last_risk_score']:.2f}")
```

---

### Troubleshoot Email Issues

```python
import os
from workflow.email_notifier import _send_smtp_alert

# Check SMTP config
print("SMTP Configuration:")
print(f"  HOST: {os.getenv('SMTP_HOST', 'NOT SET')}")
print(f"  PORT: {os.getenv('SMTP_PORT', 'NOT SET')}")
print(f"  USER: {os.getenv('SMTP_USER', 'NOT SET')}")
print(f"  PASSWORD: {'SET' if os.getenv('SMTP_PASSWORD') else 'NOT SET'}")
print(f"  FROM_EMAIL: {os.getenv('FROM_EMAIL', 'NOT SET')}")

# Test SMTP connection
test_email = "test@example.com"
success = _send_smtp_alert(
    test_email, 
    "Test Subject",
    "Test body"
)
print(f"\nTest email: {'✓ SENT' if success else '✗ FAILED'}")
```

---

## 📊 Performance Tips

### Optimize for Large Datasets

```python
# Process in batches if >1000 suppliers
batch_size = 500
alert_results = []

for i in range(0, len(predictions_df), batch_size):
    batch = predictions_df.iloc[i:i+batch_size]
    results = send_top_supplier_alerts(batch, top_n=5)
    alert_results.extend(results)
    logger.info("Processed batch %d/%d", i//batch_size + 1, 
                len(predictions_df)//batch_size + 1)
```

---

## 🎯 Integration Checklist

- [x] Workflow modules imported in run_pipeline.py
- [x] Stage 9b added between decision-support and agent
- [x] Recommendations generated and saved
- [x] Portfolio state tracked and saved
- [x] Alerts sent for top 5 suppliers
- [x] Output directory created
- [x] Portfolio summary saved as JSON
- [x] Risk predictions saved with recommendations
- [x] Alert results returned in pipeline output
- [x] All operations logged
- [x] Error handling in place

**Everything is ready to use!**

