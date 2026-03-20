from __future__ import annotations

import importlib
import logging
from contextlib import contextmanager
from typing import Iterator

from configs.settings import get_settings

LOGGER = logging.getLogger(__name__)


def is_neo4j_available() -> bool:
    """Check if Neo4j is reachable before attempting writes.
    
    Returns True only if:
    - neo4j module is available
    - credentials are configured
    - connection can be established
    - a test query succeeds
    
    Returns False otherwise (with single log message).
    """
    settings = get_settings()
    try:
        neo4j_module = importlib.import_module("neo4j")
        graph_database = getattr(neo4j_module, "GraphDatabase", None)
    except Exception:  # pragma: no cover
        return False

    if graph_database is None:
        return False
    if not (settings.neo4j_uri and settings.neo4j_username and settings.neo4j_password):
        return False

    try:
        driver = graph_database.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
        )
    except Exception:  # pragma: no cover
        LOGGER.warning("Neo4j unavailable → skipping knowledge graph stage")
        return False

    try:
        with driver.session() as session:
            session.run("RETURN 1 as test")
        driver.close()
        return True
    except Exception:  # pragma: no cover
        LOGGER.warning("Neo4j unavailable → skipping knowledge graph stage")
        try:
            driver.close()
        except Exception:  # pragma: no cover
            pass
        return False


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
    try:
        driver = graph_database.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
        )
    except Exception:  # pragma: no cover
        yield None
        return
    
    try:
        with driver.session() as session:
            yield session
    except Exception:  # pragma: no cover
        yield None
    finally:
        try:
            driver.close()
        except Exception:  # pragma: no cover
            pass
