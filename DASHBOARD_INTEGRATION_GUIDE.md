"""
DASHBOARD INTEGRATION GUIDE

This document explains the new UI sections added to dashboard.py
and how they integrate the explainability layer.

================================================================================
NEW DASHBOARD SECTIONS (4 added)
================================================================================

SECTION 10: "How Risk Score is Computed"
    Location: dashboard.py function _render_risk_score_explanation_section()
    
    Components:
    1. Formula explanation
       - Shows the weighted sum formula
       - Displays weights for each component
       - Explains rationale for each weight
    
    2. Feature contribution breakdown
       - Dropdown: Select a company
       - Displays final risk score and risk level
       - Bar chart: Features ranked by contribution
       - Table: Feature, Weight %, Contribution %
       - Plain English interpretation
    
    User Value:
    - Transparent: See exactly how score is calculated
    - Auditable: Walk through the formula with the numbers
    - Trustworthy: Understand why each feature matters
    
    Technical Details:
    - Uses RiskScoreExplainer.compute_risk_and_explanation()
    - Uses RiskScoreExplainer.explain_feature_importance()
    - Data sources: predictions_df, features_df from outputs
    - UI: st.expander, st.columns, px.bar, st.table

---

SECTION 11: "Anomaly Detection Explanation"
    Location: dashboard.py function _render_anomaly_detection_explanation_section()
    
    Components:
    1. Methodology explanation
       - Algorithm: Isolation Forest
       - Why chosen (5 reasons)
       - Parameters (n_estimators, contamination, etc.)
    
    2. Anomaly score distribution
       - Histograms: Normal vs Anomalous transactions
       - Metrics: Total, Flagged, Normal counts
       - Detection confidence score
    
    3. Threshold logic
       - Current threshold value (0.65)
       - Tradeoffs: Higher vs lower threshold
       - How threshold was empirically set
    
    4. Feature importance
       - Bar chart: Features by variance ratio
       - Shows which features most discriminate anomalies
    
    User Value:
    - Methodologically sound: Algorithm is proven, not arbitrary
    - Transparent: Understand why detection works the way it does
    - Calibratable: See threshold impact and adjust if needed
    
    Technical Details:
    - Uses AnomalyDetectionExplainer.get_methodology_explanation()
    - Uses AnomalyDetectionExplainer.feature_importance_for_anomaly_detection()
    - Data sources: anomaly_scores_df, transactions_df from outputs
    - UI: st.expander, st.columns, px.histogram, px.bar

---

SECTION 12: "Network Risk Explanation"
    Location: dashboard.py function _render_network_risk_explanation_section()
    
    Components:
    1. Network definition
       - What nodes represent (companies)
       - What edges represent (dependencies)
       - How edge weights are calculated
       - Why it matters for risk
    
    2. Centrality metrics explained
       - Degree centrality: How connected?
       - In-degree: Who depends on us?
       - Out-degree: Who do we depend on?
       - Betweenness: Are we a critical bridge?
       - PageRank: How influential?
    
    3. Top influential nodes
       - Leaderboard: Highest in-degree (many depend on them)
       - Leaderboard: Highest out-degree (many dependencies)
       - Leaderboard: Highest betweenness (critical bridges)
       - Scatter plot: In-degree vs Out-degree colored by PageRank
    
    4. Risk exposure for selected company
       - Dropdown: Select a company
       - Explanation: Why it's risky (in/out/bridge risk)
       - Metrics: In-degree count, Out-degree count, Bridge risk, Total exposure
    
    User Value:
    - Systemic view: Understand supply chain structure and contagion
    - Explainable metrics: Know what centrality scores mean
    - Node analysis: See why specific companies are critical
    
    Technical Details:
    - Uses NetworkGraphExplainer.get_network_definition()
    - Uses NetworkGraphExplainer.compute_all_centrality_metrics()
    - Uses NetworkGraphExplainer.compute_node_risk_exposure()
    - Data sources: network_df from outputs, dep_graph (NetworkX)
    - UI: st.expander, st.columns, st.dataframe, px.scatter

---

SECTION 13: "System Transparency & Limitations"
    Location: dashboard.py function _render_system_transparency_section()
    
    Components:
    1. Data source and currency
       - Where data comes from (simulated vs real)
       - How recent is the data (outputs dir only)
       - Implication: Must re-run pipeline for updates
    
    2. Model assumptions (5 documented)
       - Transaction data represents true activity
       - Historical patterns predictive (stationarity)
       - Network relationships static
       - Anomaly detection unsupervised
       - Risk is additive
    
    3. System limitations (6 documented)
       - May miss novel attack patterns
       - Assumes all edges equally important
       - Risk scores reflect data quality
       - Systemic importance backward-looking
       - LLM could hallucinate beyond context
    
    4. Incapabilities (5 documented)
       - Cannot predict black swans
       - Cannot identify sophisticated fraud alone
       - Not real-time
       - Cannot do causal inference
       - Cannot prescribe (only explains)
    
    5. Update frequency
       - Manual: after pipeline execution
       - Typical: daily or weekly
    
    6. Trust calibration
       - High confidence: Anomaly detection, network structure
       - Medium confidence: Risk formula, trends
       - Low confidence: Long-term predictions, black swans
    
    User Value:
    - Honesty: System clearly states what it can and cannot do
    - Calibration: Know when to trust and when to doubt
    - Governance: Understand data sources for compliance
    
    Technical Details:
    - Uses ExplainabilityEngine.get_system_transparency()
    - Returns SystemTransparency dataclass
    - Data sources: Configuration constants in ExplainabilityEngine
    - UI: st.subheader, st.markdown, st.warning, st.error

================================================================================
SECTION NAVIGATION
================================================================================

Sidebar updated to show 13 sections:

1. System Overview ..................... Metrics dashboard
2. Company Risk Leaderboard ............ Risk scores ranked
3. Risk Trend Visualization ............ Trends over time
4. Dependency Network Graph ............ Interactive graph
5. Transaction Anomaly Insights ........ Anomaly detection
6. Financial News Analysis ............ Events and sentiment
7. AI Query Interface .................. Q&A over data
8. FinBERT News Explanation ........... Sentiment pipeline
9. Graph Insights Panel ............... Centrality analysis

NEW:
10. How Risk Score is Computed ......... EXPLAINED FORMULA
11. Anomaly Detection Explanation ..... EXPLAINED METHOD
12. Network Risk Explanation ........... EXPLAINED EDGES & METRICS
13. System Transparency & Limitations .. DOCUMENTED ASSUMPTIONS

All sections can be toggled on/off in the sidebar.
Default: All sections displayed.

================================================================================
WORKFLOW: A USER EXPLORING THE DASHBOARD
================================================================================

User Journey 1: "Why is COMP-ALPHA's risk score 75?"
    
    1. Opens dashboard
    2. Goes to "Company Risk Leaderboard" → sees COMP-ALPHA at 75/100
    3. Wants to understand why → clicks "How Risk Score is Computed"
    4. Selects "COMP-ALPHA" from dropdown
    5. Sees formula: Risk = 25% anomaly + 20% volatility + ...
    6. Sees bar chart: anomaly frequency contributed 18.5%, network exposure 15%, etc.
    7. Reads interpretation: "COMP-ALPHA is experiencing moderate financial risk based on..."
    
    Result: User understands exactly why the score is 75, can audit the calculation.

---

User Journey 2: "Are these anomalies real or false alarms?"
    
    1. Goes to "Transaction Anomaly Insights" → sees histogram of scores
    2. Wants to understand the method → clicks "Anomaly Detection Explanation"
    3. Reads "Why Isolation Forest?": non-parametric, handles multi-dimensional, proven
    4. Sees confidence score: 85% confidence in the Isolation Forest method
    5. Sees threshold logic: 0.65 threshold flags ~4% as anomalous
    6. Sees feature importance: which features most distinguish anomalies
    
    Result: User understands it's a proven method, trusts the 85% confidence, can adjust threshold if needed.

---

User Journey 3: "Why is COMP-BETA suddenly high-risk?"
    
    1. Notices COMP-BETA moved from low to high risk in leaderboard
    2. Wants to understand network impact → "Network Risk Explanation"
    3. Sees COMP-BETA has high out-degree: depends on many suppliers
    4. Sees COMP-BETA has high betweenness: is a bridge in supply chain
    5. Selects COMP-BETA in risk exposure analysis
    6. Sees explanation: "HIGH OUT-DEGREE RISK: Depends on 23 suppliers. Vulnerable to disruptions."
    
    Result: User understands it's a network risk issue (many dependencies), not operational failure.

---

User Journey 4: "Should I trust this system?"
    
    1. Skeptical about AI-driven risk scoring
    2. Goes to "System Transparency & Limitations"
    3. Reads list of 5 explicit assumptions
    4. Reads list of 6 explicit limitations
    5. Reads list of 5 things system CANNOT do
    6. Sees warnings: "Not a substitute for human judgment"
    
    Result: User appreciates honesty, feels more confident in system (because it admits limitations).

================================================================================
TECHNICAL IMPLEMENTATION NOTES
================================================================================

IMPORT PATTERN USED:
    Try/except imports in each render function for robustness:
    ```python
    try:
        from ml_models.risk_score_explainer import RiskScoreExplainer
    except ImportError:
        st.error("RiskScoreExplainer module not found.")
        return
    ```
    This allows graceful degradation if modules aren't installed.

DATA FLOW:
    1. load_data() loads all CSVs from outputs/ directory (top-level caching)
    2. Each render function receives data dict (no re-reading)
    3. Each render function creates explainer instance (lightweight)
    4. Explainer processes data (all computation in explainer)
    5. Render function displays results (Streamlit UI)

CACHING:
    - Dashboard data cached at top level: @st.cache_data
    - Each explainer is lightweight (no caching needed)
    - Results not cached (always fresh from current data)

STYLING:
    - Uses existing theme (dark mode, Streamlit defaults)
    - Matches color scheme: #22c1aa (low), #f59e0b (medium), #ef4444 (high)
    - Uses st.expander for detailed explanations
    - Uses st.columns for side-by-side layout

ERROR HANDLING:
    - Missing data columns: st.warning()
    - Missing modules: st.error()
    - Empty dataframes: early returns with informative messages
    - Graceful degradation: if anomaly_explainer fails, display what's available

================================================================================
EXAMPLE: INTEGRATING IN YOUR PIPELINE
================================================================================

If you want to call explainability from your feature pipeline:

```python
# pipeline/compute_risk.py

from ml_models.risk_score_explainer import RiskScoreExplainer

def compute_and_explain(company_id: str, features_dict: dict) -> tuple:
    explainer = RiskScoreExplainer()
    risk_score, explanation = explainer.compute_risk_and_explanation(
        company_id=company_id,
        features_dict=features_dict,
    )
    
    # Save score
    save_to_db(company_id, risk_score)
    
    # Log explanation
    logger.info(f"{company_id}: {explanation.interpretation}")
    
    return risk_score, explanation
```

Or from your REST API:

```python
# api/endpoints.py

@app.get("/api/companies/{company_id}/risk/explanation")
def get_risk_explanation(company_id: str):
    features = get_features_from_db(company_id)
    explainer = RiskScoreExplainer()
    risk_score, explanation = explainer.compute_risk_and_explanation(company_id, features)
    
    return {
        "company_id": company_id,
        "risk_score": explanation.final_risk_score,
        "risk_level": explanation.risk_level,
        "interpretation": explanation.interpretation,
        "feature_contributions": explanation.feature_contributions,
        "formula": explanation.formula_description,
    }
```

================================================================================
TESTING THE DASHBOARD
================================================================================

To verify explainability sections work:

1. Ensure outputs/ directory exists with the required CSVs:
   - risk_predictions.csv (company_id, risk_score, risk_level, etc.)
   - features.csv (company_id, transaction_volatility, etc.)
   - anomaly_scores.csv (transaction_id, anomaly_score, anomaly_flag)
   - network_risk_analysis.csv (company_id, network_exposure_score, etc.)
   - events.csv (company_id, event_type, event_impact_score, sentiment)

2. Run dashboard:
   ```bash
   streamlit run dashboard.py
   ```

3. Check Section 10: "How Risk Score is Computed"
   - Formula should display
   - Company dropdown should populate
   - Bar chart should show contributions
   - Score should match formula

4. Check Section 11: "Anomaly Detection Explanation"
   - Algorithm description should display
   - Score distribution histogram should render
   - Feature importance should compute

5. Check Section 12: "Network Risk Explanation"
   - Network definition should display
   - Centrality metrics explainer should show
   - Company dropdown should work
   - Exposure metrics should compute

6. Check Section 13: "System Transparency"
   - All 5 assumptions should list
   - All 6 limitations should list
   - All 5 incapabilities should list
   - Warnings should display

================================================================================
"""
