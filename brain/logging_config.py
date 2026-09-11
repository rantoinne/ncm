"""Central logging setup for the NCM Python brain."""

from __future__ import annotations

import logging
import os
import sys
from typing import Literal

LevelName = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

_CONFIGURED = False


def parse_level(name: str | None) -> int:
    if not name:
        return logging.INFO
    return getattr(logging, name.strip().upper(), logging.INFO)


def setup_logging(
    *,
    level: str | None = None,
    json_logs: bool | None = None,
    name: str = "ncm",
) -> logging.Logger:
    """
    Configure root + ncm loggers once.

    Env:
      NCM_LOG_LEVEL   — DEBUG|INFO|WARNING|ERROR (default INFO)
      NCM_LOG_FORMAT  — json|text (default text)
    """
    global _CONFIGURED
    level_name = (level or os.getenv("NCM_LOG_LEVEL") or "INFO").upper()
    use_json = json_logs
    if use_json is None:
        use_json = os.getenv("NCM_LOG_FORMAT", "text").lower() == "json"

    root = logging.getLogger()
    if not _CONFIGURED:
        root.handlers.clear()
        handler = logging.StreamHandler(sys.stderr)
        if use_json:
            handler.setFormatter(
                logging.Formatter(
                    '{"level":"%(levelname)s","logger":"%(name)s","msg":%(message)s,'
                    '"time":"%(asctime)s"}'
                )
            )
        else:
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
                    datefmt="%H:%M:%S",
                )
            )
        root.addHandler(handler)
        _CONFIGURED = True

    root.setLevel(parse_level(level_name))
    logger = logging.getLogger(name)
    logger.setLevel(parse_level(level_name))
    # Quiet noisy deps unless debugging
    if parse_level(level_name) > logging.DEBUG:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("neo4j").setLevel(logging.WARNING)
    return logger


def get_logger(name: str = "ncm") -> logging.Logger:
    if not _CONFIGURED:
        setup_logging()
    return logging.getLogger(name)
