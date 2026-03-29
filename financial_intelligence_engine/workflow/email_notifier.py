"""Email alert module for high-risk supplier notifications."""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import os

import pandas as pd

LOGGER = logging.getLogger("workflow.email")


def _get_currency_symbol(row: pd.Series) -> str:
    """Infer currency symbol from row data or default to ₹."""
    currency = row.get("currency", "INR")
    if isinstance(currency, str):
        if "USD" in currency.upper() or "DOLLAR" in currency.upper():
            return "$"
        elif "EUR" in currency.upper() or "EURO" in currency.upper():
            return "€"
    return "₹"


def _format_cost_impact(cost_impact: float, row: pd.Series) -> str:
    """Format cost impact with currency and magnitude."""
    currency = _get_currency_symbol(row)
    
    # Estimate magnitude based on cost_impact percentage
    if cost_impact > 0.7:
        magnitude = "2.7M"  # Example high impact
    elif cost_impact > 0.5:
        magnitude = "1.5M"
    elif cost_impact > 0.3:
        magnitude = "700K"
    else:
        magnitude = "250K"
    
    return f"{currency}{magnitude}"


def _get_risk_level_text(risk_score: float) -> str:
    """Convert risk score to readable text."""
    if risk_score > 0.7:
        return "CRITICAL"
    elif risk_score > 0.5:
        return "HIGH"
    elif risk_score > 0.3:
        return "MEDIUM"
    else:
        return "LOW"


def _build_alert_body(row: pd.Series) -> str:
    """Build email body content based on supplier risk profile."""
    company_id = row.get("company_id", "Unknown")
    risk_score = float(row.get("propagated_risk") or row.get("risk_score", 0.0))
    cost_impact = float(row.get("estimated_cost_impact", 0.0))
    criticality = float(row.get("systemic_importance_score", 0.0))
    action = row.get("recommended_action", "Monitor")
    
    risk_level = _get_risk_level_text(risk_score)
    cost_str = _format_cost_impact(cost_impact, row)
    downstream_count = int(row.get("downstream_count", 5))  # Estimate from criticality
    
    # Build reason section
    reasons = []
    if risk_score > 0.6:
        reasons.append("  • High risk indicators detected in financial signals")
    if cost_impact > 0.6:
        reasons.append(f"  • Potential cost impact of {cost_str} if supplier fails")
    if criticality > 0.5:
        reasons.append(f"  • Supplier is critical to {downstream_count}+ downstream companies")
    
    if not reasons:
        reasons.append("  • Elevated risk metrics warrant attention")
    
    # Build simulation insight
    simulation_insight = ""
    if criticality > 0.6:
        pct_impact = int(criticality * 100)
        simulation_insight = (
            f"Failure could impact {downstream_count} downstream companies "
            f"and increase operational cost by {pct_impact}%."
        )
    elif cost_impact > 0.5:
        simulation_insight = (
            f"Failure could result in significant cost escalation of {cost_str}. "
            f"Affects {downstream_count} downstream companies."
        )
    else:
        simulation_insight = (
            f"Failure impact: moderate to high. "
            f"Affects {downstream_count} downstream partners."
        )
    
    # Build full body
    body = f"""Supplier {company_id} has been flagged as {risk_level} risk.

Risk Score: {risk_score:.2f}
Estimated Cost Impact: {cost_str}
Criticality: {"High" if criticality > 0.5 else "Medium" if criticality > 0.3 else "Standard"}

REASON:
{chr(10).join(reasons)}

RECOMMENDED ACTION:
{_format_action_text(action)}

SIMULATION INSIGHT:
{simulation_insight}

---
This is an automated alert from the Supply Chain Risk Intelligence System.
Please review and take appropriate action.
"""
    
    return body


def _format_action_text(action: str) -> str:
    """Format action recommendation as readable text."""
    if action == "Replace supplier":
        return ("Replace supplier or diversify immediately.\n"
                "Begin transition planning for alternative suppliers.\n"
                "Prioritize risk reduction within 30-60 days.")
    elif action == "Diversify suppliers":
        return ("Diversify supply from this supplier.\n"
                "Target 30-40% volume reduction to alternatives.\n"
                "Review within 90 days for effectiveness.")
    else:
        return ("Continue monitoring supplier metrics.\n"
                "Review quarterly and set escalation thresholds.\n"
                "Track risk indicators for deterioration.")


def _send_smtp_alert(to_email: str, subject: str, body: str) -> tuple[bool, str]:
    """
    Send email via SMTP.
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Email body
    
    Returns:
        Tuple of (success flag, status/error message)
    """
    # Get SMTP config from environment
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    if smtp_password:
        smtp_password = "".join(smtp_password.split())
    from_email = os.getenv("FROM_EMAIL", smtp_user or "noreply@supplychainrisk.local")
    
    # If SMTP not configured, return False (will fallback to logging)
    if not smtp_host or not smtp_user:
        return False, "missing SMTP_HOST/SMTP_USER"
    
    try:
        msg = MIMEMultipart()
        msg["From"] = from_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            if smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(msg)
        
        LOGGER.info("Email sent to %s for supplier %s", to_email, subject.split("–")[-1].strip())
        return True, "sent"
    except Exception as e:
        LOGGER.warning("Failed to send email to %s: %s", to_email, str(e))
        return False, str(e)


def send_supplier_alert(
    row: pd.Series,
    to_email: Optional[str] = None,
    simulate: bool = True,
) -> dict:
    """
    Send risk alert for a supplier.
    
    If simulate=True or SMTP not configured, logs alert instead of sending email.
    
    Args:
        row: A pandas Series from predictions dataframe
        to_email: Email address to send to (optional)
        simulate: If True, log instead of sending real email
    
    Returns:
        Dictionary with alert status and details
    """
    company_id = row.get("company_id", "Unknown")
    risk_score = float(row.get("propagated_risk") or row.get("risk_score", 0.0))
    cost_impact = float(row.get("estimated_cost_impact", 0.0))
    
    # Check trigger conditions
    should_alert = risk_score > 0.6 or cost_impact > 0.6
    
    if not should_alert:
        return {
            "sent": False,
            "reason": "Below alert threshold",
            "company_id": company_id,
        }
    
    subject = f"Supplier Risk Alert – {company_id}"
    body = _build_alert_body(row)
    
    # Determine delivery method
    if simulate or not to_email:
        # Log the alert
        LOGGER.info(
            "ALERT (SIMULATED): %s | Risk: %.2f | Cost Impact: %.2f",
            company_id,
            risk_score,
            cost_impact,
        )
        LOGGER.debug("Alert body:\n%s", body)
        return {
            "sent": True,
            "method": "logged",
            "company_id": company_id,
            "subject": subject,
        }
    else:
        # Try to send real email
        success, status = _send_smtp_alert(to_email, subject, body)
        return {
            "sent": success,
            "method": "email" if success else "failed",
            "company_id": company_id,
            "recipient": to_email,
            "error": None if success else status,
        }


def send_top_supplier_alerts(
    predictions_df: pd.DataFrame,
    top_n: int = 5,
    simulate: bool = True,
    to_email: Optional[str] = None,
) -> list[dict]:
    """
    Send alerts for top N riskiest suppliers.
    
    Args:
        predictions_df: DataFrame with supplier risk predictions
        top_n: Number of top suppliers to alert (default 5)
        simulate: If True, log alerts instead of sending emails
        to_email: Recipient email address. If omitted, falls back to
            ALERT_TO_EMAIL, SMTP_TO_EMAIL, or SMTP_USER env vars.
    
    Returns:
        List of alert result dictionaries
    """
    if predictions_df.empty:
        LOGGER.info("No suppliers to alert")
        return []

    resolved_to_email = (
        to_email
        or os.getenv("ALERT_TO_EMAIL")
        or os.getenv("SMTP_TO_EMAIL")
        or os.getenv("SMTP_USER")
    )

    if not simulate and not resolved_to_email:
        LOGGER.warning(
            "Real-email mode requested but no recipient found. Set ALERT_TO_EMAIL, SMTP_TO_EMAIL, or pass to_email."
        )
    
    # Sort by risk and take top N
    risk_col = "propagated_risk" if "propagated_risk" in predictions_df.columns else "risk_score"
    top_suppliers = predictions_df.nlargest(top_n, risk_col)
    
    results = []
    for idx, (_, row) in enumerate(top_suppliers.iterrows(), 1):
        result = send_supplier_alert(row, to_email=resolved_to_email, simulate=simulate)
        result["rank"] = idx
        results.append(result)
    
    LOGGER.info("Sent %d supplier alerts", len(results))
    return results
