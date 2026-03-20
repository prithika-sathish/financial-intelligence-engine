"""
EXPLAINABILITY & TRANSPARENCY LAYER - IMPLEMENTATION GUIDE

This document explains the explainability features added to the financial risk analytics system.

================================================================================
OVERVIEW
================================================================================

The system now includes complete transparency across all components:

1. ✅ Risk Score Engine - Decomposable into feature contributions
2. ✅ Anomaly Detection - Method explained, confidence scores computed
3. ✅ Network Graph - Edges defined, centrality metrics explained
4. ✅ AI Query Interface - Rule-based grounding (no hallucinations)
5. ✅ System Transparency - Data sources, limitations, assumptions documented

Every number shown in the UI is traceable to a computation.
No random or hardcoded outputs.

================================================================================
PART 1: RISK SCORE ENGINE
================================================================================

FILE: ml_models/explainability.py + ml_models/risk_score_explainer.py

FORMULA (Weighted Sum):
    Risk Score = Σ(feature_value × weight × 100)
    
where:
    - Each feature is normalized to [0, 1]
    - Weights sum to 1.0 (ensures interpretability)
    - Result scaled to 0-100

WEIGHTS:
    - Transaction Volatility: 20%
    - Anomaly Frequency: 25%
    - Credit/Debt Signals: 15%
    - Network Exposure: 25%
    - Event Impact: 15%

FEATURES COMPUTED:

1. Transaction Volatility
   Definition: std_dev(transaction_amounts) / mean(transaction_amounts)
   Range: [0, 1] clamped
   Why: Sudden spikes in transaction size indicate liquidity stress
   Source: transactions_df (amount column)

2. Anomaly Frequency
   Definition: % of anomalous transactions for this company
   Range: [0, 1] (already a percentage)
   Why: High anomaly % = unusual activity; possible fraud/stress
   Source: anomaly_scores_df (anomaly_flag column)

3. Credit/Debt Signals
   Definition: Supplier concentration (Herfindahl-Hirschman Index)
   Range: [0, 1]
   Why: High concentration = dependency risk on few suppliers
   Source: transactions_df (supplier_id column, grouped by company)

4. Network Exposure
   Definition: Degree centrality in supply chain network
   Range: [0, 1] (normalized by max possible connections)
   Why: Central nodes fail = wider impact; vulnerable to disruptions
   Source: graph_metrics_df (network_exposure_score or degree_centrality)

5. Event Impact
   Definition: Max impact score from recent events + negative sentiment ratio
   Range: [0, 1]
   Why: Recent negative news = forward-looking risk signal
   Source: events_df (event_impact_score and sentiment columns)

OUTPUT:
    RiskScoreExplanation dataclass containing:
    - final_risk_score (0-100)
    - risk_level ("low", "medium", "high")
    - feature_contributions (dict)
    - feature_weights (dict)
    - formula_description (textual)
    - interpretation (plain English)

UI SECTION: "How Risk Score is Computed"
    - Shows formula
    - Explains each weight
    - Displays feature contribution breakdown for selected company
    - Bar chart: features by contribution
    - Table: feature, weight, contribution
    - Plain English interpretation

================================================================================
PART 2: ANOMALY DETECTION TRANSPARENCY
================================================================================

FILE: ml_models/explainability.py + ml_models/anomaly_explainer.py

ALGORITHM: Isolation Forest (scikit-learn)

WHY ISOLATION FOREST?
    1. Non-parametric: no assumption of normal distribution
    2. Handles multi-dimensional data (many transaction features)
    3. Detects both global and local outliers
    4. Computationally efficient
    5. Proven effective in fraud detection literature

PARAMETERS:
    - n_estimators: 100 (trees in forest)
    - contamination: 0.04 (expect ~4% anomalies)
    - max_samples: "auto" (√n samples per tree)
    - random_state: 42 (reproducibility)

THRESHOLD:
    - anomaly_score ≥ 0.65 → flag as anomalous
    - Lower threshold: catch more anomalies, more false alarms
    - Higher threshold: fewer false alarms, miss subtle anomalies
    - Current setting: empirically balanced

CONFIDENCE SCORE:
    For each transaction flagged as anomalous:
    - Confidence = sigmoid(anomaly_score) if flagged
    - Confidence = 1 - sigmoid(anomaly_score) if normal
    - Higher confidence = more certain in the classification

FEATURE IMPORTANCE:
    Approximated by variance ratio:
    importance = variance(anomalous) / variance(normal)
    Higher ratio = feature more discriminative for anomalies

OUTPUT:
    AnomalyExplanation dataclass containing:
    - method (algorithm name)
    - parameters (dict)
    - contamination_rate (expected % of outliers)
    - threshold (0-1)
    - reasoning (why chosen)
    - confidence_score (0-1, method confidence)

UI SECTION: "Anomaly Detection Explanation"
    - Algorithm explanation
    - Why Isolation Forest chosen
    - Anomaly score distribution histogram
    - Normal vs anomalous transaction counts
    - Threshold interpretation
    - Feature importance bar chart
    - Confidence metrics

================================================================================
PART 3: NETWORK GRAPH MEANING
================================================================================

FILE: ml_models/explainability.py + ml_models/network_explainer.py

NETWORK STRUCTURE:
    Nodes: Companies
    Edges: Company A → Company B means A depends on B (buys from B)
    Edge Weight: Fraction of A's spending going to B
        weight = amount(A→B) / total_spending(A)

WHY THIS REPRESENTATION?
    - Shows supply chain dependencies clearly
    - Edge weight indicates intensity of dependency
    - High weight: B's default disrupts A significantly
    - Enables centrality analysis to identify critical nodes

CENTRALITY METRICS:

1. Degree Centrality
   Definition: (in_degree + out_degree) / (2 × (n-1))
   Meaning: How connected overall
   Risk: Connected hubs = critical to network; failure affects many

2. In-Degree Centrality
   Definition: in_degree / (n-1)
   Meaning: How many depend on this node?
   Risk: High = many downstream entities depend on us; our failure cascades

3. Out-Degree Centrality
   Definition: out_degree / (n-1)
   Meaning: How many suppliers do we depend on?
   Risk: High = vulnerable to multiple disruption sources

4. Betweenness Centrality
   Definition: Fraction of shortest paths passing through this node
   Meaning: Is this a critical bridge/intermediary?
   Risk: High = critical for network flow; failure fragments supply chain

5. PageRank
   Definition: Importance in transaction flow (weighted by edge values)
   Meaning: Influential in financial decisions/supply chain
   Risk: High = concentrated importance; failure amplified

SYSTEMIC IMPORTANCE:
    Combined score = f(degree, betweenness, risk_score)
    High systemic importance = critical to overall system health

RISK CLUSTERS:
    Communities detection identifies tightly connected groups
    Nodes in same cluster = correlated risk; disruption cascades within cluster

OUTPUT:
    NetworkExplanation dataclass containing:
    - edge_type (what edges represent)
    - definition (plain English)
    - weight_calculation (how edges weighted)
    - risk_interpretation (why centrality matters)
    - centrality_metrics (dict per company)

UI SECTION: "Network Risk Explanation"
    - Definition of nodes, edges, weights
    - Explanation of each centrality metric
    - Top nodes by IN-DEGREE (many depend)
    - Top nodes by OUT-DEGREE (many dependencies)
    - Top nodes by BETWEENNESS (critical bridges)
    - Scatter plot: IN-DEGREE vs OUT-DEGREE (colored by PageRank)
    - Risk exposure analysis for selected company
    - IN/OUT/Bridge/Total exposure scores

================================================================================
PART 4: GROUNDED AI QUERY INTERFACE
================================================================================

FILE: ml_models/explainability.py (ground_ai_query method)

PRINCIPLE: Rule-based retrieval from computed metrics
    NOT LLM hallucination; ONLY data from actual computations

RULES IMPLEMENTED:

Rule 1: Increasing Risk Pattern
    Trigger: "increasing", "rising", "growing", "trending up"
    Response: List companies where risk_trend == "increasing"
    Grounding: risk_velocity > 0 (first derivative)

Rule 2: Systemic Importance / Contagion
    Trigger: "systemic", "contagion", "cascade", "critical"
    Response: Top 3 companies by systemic_importance_score
    Grounding: Computed from network centrality × risk × network_exposure

Rule 3: Highest Risk Companies
    Trigger: "highest risk", "most risk", "at-risk", "riskiest"
    Response: Top 3 companies by propagated_risk
    Grounding: Computed from risk formula + propagation through network

Rule 4: Recent Events Impact
    Trigger: "event", "news", "trigger"
    Response: Recent events and affected companies
    Grounding: events_df (indexed by timestamp and company_id)

Default Response:
    If question doesn't match any rule:
    Return "insufficient data" rather than hallucinate

OUTPUT:
    Dictionary with:
    - answer (grounded response from data)
    - evidence (what data was used)
    - reasoning (how the answer was derived)
    - confidence (0-1, trustworthiness)
    - method ("rule-based")

WORKFLOW:
    1. User asks question
    2. System checks against rule patterns
    3. If match: retrieve data for that rule
    4. Return grounded response with evidence
    5. If no match: decline to answer (no hallucination)

UI SECTION: Updated "AI Query Interface"
    - Shows method used (rule-based, not LLM hallucination)
    - Shows evidence for response
    - Shows confidence score
    - Shows reasoning path

================================================================================
PART 5: GLOBAL SYSTEM TRANSPARENCY
================================================================================

FILE: ml_models/explainability.py (get_system_transparency method)

TRANSPARENCY DOCUMENTATION:

Data Source:
    - "Simulated sample data for demonstration"
    - In production: replace with real transaction feeds
    - Implications: outputs reflect historical data only

Data Currency:
    - "Dashboard reads outputs files only. No real-time updates without pipeline execution."
    - To get latest: re-run ML pipeline

Model Assumptions:
    1. Transaction data represents true company financial activity
    2. Historical patterns predictive of near-term risk (stationarity)
    3. Network relationships are static (no dynamic re-weighting)
    4. Anomaly detection uses unsupervised learning (no labeled fraud in training)
    5. Risk is additive across factors (not multiplicative)

Limitations:
    1. Anomaly detection may miss novel attack patterns
    2. Network analysis assumes all edges equally important (no validation weighting)
    3. Risk scores reflect data quality (garbage in = garbage out)
    4. Systemic importance backward-looking; cannot predict supply chain pivots
    5. LLM explanations may hallucinate beyond JSON context

Not Capable Of:
    1. Predicting black swan events (by definition)
    2. Identifying money laundering/sophisticated fraud without domain experts
    3. Real-time detection (needs pipeline execution)
    4. Causal inference (correlation ≠ causation)
    5. Prescriptive recommendations (explains, does not advise)

Update Frequency:
    "Manual: after running ML pipeline. Typical: daily or weekly batch."

Trust Calibration:
    High confidence: Anomaly detection, network structure analysis
    Medium confidence: Risk formula, trend extrapolation
    Low confidence: Long-term predictions, causal inference, black swans

UI SECTION: "System Transparency & Limitations"
    - Data source and currency
    - Full list of 5 assumptions
    - Full list of 6 limitations
    - Full list of 5 incapabilities
    - Update frequency
    - Trust calibration guide
    - ⚠️ Warnings about when NOT to rely on system
    - ❌ Clear statement: NOT a substitute for human judgment

================================================================================
CODE ORGANIZATION
================================================================================

ml_models/explainability.py (450+ lines)
    Core ExplainabilityEngine class with:
    - RISK_FORMULA_WEIGHTS (constant)
    - ANOMALY_METHOD, ANOMALY_CONTAMINATION, ANOMALY_THRESHOLD (constants)
    - NETWORK_EDGE_TYPE, NETWORK_EDGE_DEFINITION (constants)
    - explain_risk_score()
    - explain_anomaly_detection()
    - explain_network_graph()
    - ground_ai_query()
    - get_system_transparency()
    Data classes:
    - RiskScoreExplanation
    - AnomalyExplanation
    - NetworkExplanation
    - SystemTransparency

ml_models/risk_score_explainer.py (200+ lines)
    RiskScoreExplainer class with:
    - compute_risk_and_explanation()
    - _normalize_features()
    - _compute_weighted_risk()
    - explain_feature_importance()
    - build_features_from_data()
    - explain_batch()

ml_models/anomaly_explainer.py (250+ lines)
    AnomalyDetectionExplainer class with:
    - get_methodology_explanation()
    - detect_anomalies() [wraps Isolation Forest]
    - add_anomaly_explanations()
    - analyze_anomaly_distribution()
    - explain_at_threshold()
    - feature_importance_for_anomaly_detection()

ml_models/network_explainer.py (350+ lines)
    NetworkGraphExplainer class with:
    - get_network_definition()
    - build_supply_chain_network()
    - compute_all_centrality_metrics()
    - compute_node_risk_exposure()
    - identify_risk_clusters()
    - explain_node_in_context()

dashboard.py (additions)
    New UI sections:
    - _render_risk_score_explanation_section()
    - _render_anomaly_detection_explanation_section()
    - _render_network_risk_explanation_section()
    - _render_system_transparency_section()
    - Added 4 new sections to sidebar navigation

================================================================================
USAGE EXAMPLES
================================================================================

EXAMPLE 1: Explain Risk Score for a Company

```python
from ml_models.risk_score_explainer import RiskScoreExplainer

explainer = RiskScoreExplainer()

# Build features from raw data
features = explainer.build_features_from_data(
    company_id="COMP-ALPHA",
    transactions_df=transactions_df,
    anomaly_scores_df=anomaly_scores_df,
    events_df=events_df,
    graph_metrics_df=graph_metrics_df,
)

# Get risk score and explanation
risk_score, explanation = explainer.compute_risk_and_explanation(
    company_id="COMP-ALPHA",
    features_dict=features,
)

# Display contribution breakdown
contrib_df = explainer.explain_feature_importance(explanation)
print(contrib_df)
# Output:
#          feature  weight  weight_pct  contribution  contribution_pct
#   anomaly_frequency     0.25       25%          18.5            18.5%
# network_exposure     0.25       25%          12.3            12.3%
# ...

print(explanation.interpretation)
# "Risk score of 67.2/100 (medium). Top drivers: anomaly_frequency (18.5%), network_exposure (12.3%), ..."
```

EXAMPLE 2: Detect Anomalies and Explain

```python
from ml_models.anomaly_explainer import AnomalyDetectionExplainer

explainer = AnomalyDetectionExplainer()

# Detect anomalies
anomaly_flags, anomaly_scores = explainer.detect_anomalies(features_df)

# Add confidence and explanations
transactions_explained = explainer.add_anomaly_explanations(
    transactions_df, anomaly_flags, anomaly_scores
)

# Analyze distribution
distribution = explainer.analyze_anomaly_distribution(anomaly_scores, anomaly_flags)
print(f"Flagged: {distribution['flagged_anomalies']} / {distribution['total_transactions']}")
print(f"Score separation: {distribution['score_separation']:.3f}")

# Threshold interpretation
threshold_analysis = explainer.explain_at_threshold(anomaly_scores, threshold=0.65)
print(threshold_analysis["explanation"])
# "Setting threshold to 0.65 flags 3.2% of transactions..."
```

EXAMPLE 3: Network Centrality Analysis

```python
from ml_models.network_explainer import NetworkGraphExplainer

explainer = NetworkGraphExplainer()

# Build network
network = explainer.build_supply_chain_network(
    transactions_df=transactions_df,
    risk_predictions_df=risk_predictions_df,
)

# Compute all centrality metrics
centrality_df = explainer.compute_all_centrality_metrics(network)

# Analyze specific node
exposure = explainer.compute_node_risk_exposure(network, "COMP-ALPHA")
print(exposure["explanation"])
# "HIGH IN-DEGREE RISK: 12 companies depend on COMP-ALPHA. Default would trigger cascading failures."

# Identify clusters
clusters = explainer.identify_risk_clusters(network)
print(clusters)
# {"cluster_0": ["COMP-A", "COMP-B", "COMP-C"], "cluster_1": [...]}
```

EXAMPLE 4: Ground AI Query

```python
from ml_models.explainability import ExplainabilityEngine

engine = ExplainabilityEngine()

# Answer a question
result = engine.ground_ai_query(
    question="Which companies show increasing financial risk?",
    predictions_df=predictions_df,
    network_df=network_df,
    trends_df=trends_df,
    events_df=events_df,
)

print(result["answer"])
# "Companies with increasing risk: COMP-ALPHA, COMP-BETA, COMP-GAMMA"

print(result["reasoning"])
# "Based on risk_trend calculation: risk_velocity > 0"

print(f"Confidence: {result['confidence']}")
# "Confidence: 0.95"
```

================================================================================
INTEGRATION POINTS
================================================================================

DASHBOARD:
    Sections 10-13 are all new explainability sections
    - Render functions import from ml_models
    - Data flows from cached DataFrames
    - UI displays outputs from explainer classes

PIPELINE:
    The explainability layer is READ-ONLY
    - Does not modify data
    - Does not affect upstream computations
    - Can be integrated at any stage after feature computation

API:
    Endpoints can return explanations:
    - GET /api/risk/{company_id}/explanation
    - GET /api/anomaly/{transaction_id}/explanation
    - GET /api/network/centrality
    - GET /api/ai/query?question=...

================================================================================
TESTING EXPLAINABILITY
================================================================================

All explainability functions are:
    ✅ Deterministic (same input → same output)
    ✅ Traceable (can follow computation step-by-step)
    ✅ Auditable (every number linked to a formula)
    ✅ Reproducible (seed parameter in randomness)

To verify a risk score:
    1. Get explanation output
    2. Manually compute: Σ(feature_value × weight × 100)
    3. Should match final_risk_score ±0.01 (floating point tolerance)

To verify anomaly detection:
    1. Get score from Isolation Forest
    2. Apply sigmoid normalization
    3. Compare to anomaly_score in output
    4. Apply threshold
    5. Should match anomaly_flag

To verify network metrics:
    1. Build NetworkX graph
    2. Compute centrality using nx.degree_centrality(), etc.
    3. Compare to output from compute_all_centrality_metrics()
    4. Should match ±0.001

================================================================================
PRODUCTION DEPLOYMENT
================================================================================

DEPENDENCIES:
    - scikit-learn (Isolation Forest)
    - networkx (graph metrics)
    - pandas (DataFrame operations)
    - numpy (numerical operations)
    All already in requirements.txt

PERFORMANCE:
    - Risk score computation: O(n) where n = number of features (5)
    - Anomaly detection: O(k log m) where k = #trees, m = #features
    - Network metrics: O(n²) for small graphs (100-1000 nodes)
    - All subsecond for typical use cases

PRODUCTION CHECKLIST:
    ☐ Replace simulated data with real transaction feeds
    ☐ Update data_source in SystemTransparency
    ☐ Validate risk formula weights with domain experts
    ☐ Calibrate anomaly detection contamination rate for your data
    ☐ Test feature and anomaly confidence scores with labeled data
    ☐ Integrate with monitoring/logging system
    ☐ Add audit logging for every explanation generated
    ☐ Set up explainability metrics dashboard
    ☐ Document formula changes in version control

================================================================================
"""
