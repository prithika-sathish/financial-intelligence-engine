from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TransactionRecord(BaseModel):
    transaction_id: str
    company_id: str
    supplier_id: str
    account_id: str
    amount: float
    currency: str = "USD"
    timestamp: datetime
    description: str = ""


class NewsRecord(BaseModel):
    news_id: str
    company_id: str | None = None
    source: str = ""
    published_at: datetime
    headline: str
    body: str


class IngestionResponse(BaseModel):
    rows_ingested: int
    normalized_columns: list[str]
    sample: list[dict[str, Any]] = Field(default_factory=list)
