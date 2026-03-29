from __future__ import annotations

from typing import Iterable

import pandas as pd

from data_ingestion.schemas import NewsRecord, TransactionRecord


def load_transactions(records: Iterable[dict]) -> pd.DataFrame:
    parsed = [TransactionRecord(**row).model_dump() for row in records]
    df = pd.DataFrame(parsed)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "transaction_id",
                "company_id",
                "supplier_id",
                "account_id",
                "amount",
                "currency",
                "timestamp",
                "description",
            ]
        )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    return df


def load_news(records: Iterable[dict]) -> pd.DataFrame:
    parsed = [NewsRecord(**row).model_dump() for row in records]
    df = pd.DataFrame(parsed)
    if df.empty:
        return pd.DataFrame(
            columns=["news_id", "company_id", "source", "published_at", "headline", "body"]
        )
    df["published_at"] = pd.to_datetime(df["published_at"], utc=True)
    return df
