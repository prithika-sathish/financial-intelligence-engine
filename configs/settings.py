from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    neo4j_uri: str = os.getenv("NEO4J_URI", "")
    neo4j_username: str = os.getenv("NEO4J_USERNAME", "")
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    finbert_model: str = os.getenv("FINBERT_MODEL", "yiyanghkust/finbert-tone")


def get_settings() -> Settings:
    return Settings()
