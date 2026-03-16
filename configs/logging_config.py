from __future__ import annotations

import logging

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    """Configure project-wide logging once with a consistent format."""
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format=LOG_FORMAT)
    else:
        root.setLevel(level)
