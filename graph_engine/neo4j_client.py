from __future__ import annotations

import importlib
from contextlib import contextmanager
from typing import Iterator

from configs.settings import get_settings


@contextmanager
def neo4j_session() -> Iterator[object | None]:
    settings = get_settings()
    try:
        neo4j_module = importlib.import_module("neo4j")
        graph_database = getattr(neo4j_module, "GraphDatabase", None)
    except Exception:  # pragma: no cover
        graph_database = None

    if graph_database is None:
        yield None
        return
    if not (settings.neo4j_uri and settings.neo4j_username and settings.neo4j_password):
        yield None
        return
    driver = graph_database.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    )
    try:
        with driver.session() as session:
            yield session
    finally:
        driver.close()
